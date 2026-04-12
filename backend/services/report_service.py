"""
report_service.py — HTML 报告生成服务
生成单任务的离线 HTML 对比报告，包含：
  - 任务基本信息
  - 所有配对结果列表（状态徽章 + A/B 缩略图 + diff 图）
  - 点击行展开内联对比详情（A/B 原图并排 + 差异图）
  - 图片以 Base64 内嵌（< 50MB 时）或 URL 直连（>= 50MB 时）
"""
import base64
import io
import datetime
from typing import Optional
from sqlalchemy.orm import Session

from models import Task, Image, DiffResult
from services.oss_service import client as minio_client, BUCKET, get_public_url

SIZE_LIMIT_BYTES = 50 * 1024 * 1024   # 50 MB


def _fetch_image_b64(oss_key: str) -> Optional[str]:
    """从 MinIO 下载图片并返回 base64 data URI，失败返回 None"""
    try:
        resp = minio_client.get_object(BUCKET, oss_key)
        data = resp.read()
        resp.close()
        ext = oss_key.rsplit(".", 1)[-1].lower()
        mime = {
            "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "png": "image/png", "webp": "image/webp",
            "gif": "image/gif",
        }.get(ext, "image/png")
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:{mime};base64,{b64}"
    except Exception:
        return None


def _estimate_size(db: Session, task_id: int) -> int:
    """粗估报告中图片总字节数（原图 + diff图）"""
    images = db.query(Image).filter(Image.task_id == task_id).all()
    diffs  = db.query(DiffResult).filter(DiffResult.task_id == task_id, DiffResult.status == "done").all()

    total = 0
    def _get_size(oss_key: str) -> int:
        try:
            stat = minio_client.stat_object(BUCKET, oss_key)
            return stat.size
        except Exception:
            return 0

    for img in images:
        key = img.thumb_oss_key or img.oss_key
        total += _get_size(key)
    for d in diffs:
        if d.diff_oss_key:
            total += _get_size(d.diff_oss_key)
    return total


def generate_report(db: Session, task_id: int) -> tuple[bytes, bool]:
    """
    生成 HTML 报告。
    返回 (html_bytes, is_oversized)
      is_oversized=True 表示图片改用 URL 模式（超过 50MB）
    """
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise ValueError(f"任务 {task_id} 不存在")

    images_a = sorted(
        db.query(Image).filter(Image.task_id == task_id, Image.group == "A").all(),
        key=lambda x: x.sort_order,
    )
    images_b = sorted(
        db.query(Image).filter(Image.task_id == task_id, Image.group == "B").all(),
        key=lambda x: x.sort_order,
    )
    diff_map: dict[tuple[int, int], DiffResult] = {}
    for d in db.query(DiffResult).filter(DiffResult.task_id == task_id).all():
        diff_map[(d.image_a_id, d.image_b_id)] = d

    pair_count = max(len(images_a), len(images_b))

    # 判断是否超限
    estimated = _estimate_size(db, task_id)
    use_url = estimated >= SIZE_LIMIT_BYTES

    def img_src(oss_key: Optional[str], fallback_url: Optional[str]) -> str:
        if not oss_key:
            return fallback_url or ""
        if use_url:
            return get_public_url(oss_key)
        return _fetch_image_b64(oss_key) or get_public_url(oss_key)

    # 构建配对数据
    pairs_html = ""
    for i in range(pair_count):
        img_a = images_a[i] if i < len(images_a) else None
        img_b = images_b[i] if i < len(images_b) else None

        diff = diff_map.get((img_a.id, img_b.id)) if img_a and img_b else None

        score = diff.diff_score if diff else None
        is_similar = getattr(diff, 'is_similar', None) if diff else None
        status = diff.status if diff else "pending"
        size_warn = diff.size_warning if diff else False
        diff_oss_key = diff.diff_oss_key if diff else None

        # 徽章：优先用 score 判断（is_similar 旧数据可能为 None）
        # 阈值 0.75，< 0.75 → 异常，>= 0.75 → 正常
        if status in ("pending", "running"):
            badge = '<span class="badge pending">待计算</span>'
        elif status == "failed" or size_warn:
            badge = '<span class="badge warning">异常</span>'
        elif score is not None:
            if score < 0.75:
                badge = '<span class="badge different">异常</span>'
            else:
                badge = '<span class="badge similar">正常</span>'
        elif is_similar is not None:
            badge = ('<span class="badge similar">正常</span>' if is_similar
                     else '<span class="badge different">异常</span>')
        else:
            badge = '<span class="badge pending">待计算</span>'

        # 缩略图 src（用缩略图减少体积）
        thumb_a_src = img_src(img_a.thumb_oss_key or img_a.oss_key if img_a else None,
                               get_public_url(img_a.oss_key) if img_a else None)
        thumb_b_src = img_src(img_b.thumb_oss_key or img_b.oss_key if img_b else None,
                               get_public_url(img_b.oss_key) if img_b else None)

        # 原图 src（detail 区用大图）
        full_a_src = img_src(img_a.oss_key if img_a else None,
                              get_public_url(img_a.oss_key) if img_a else None)
        full_b_src = img_src(img_b.oss_key if img_b else None,
                              get_public_url(img_b.oss_key) if img_b else None)
        diff_src   = img_src(diff_oss_key,
                              get_public_url(diff_oss_key) if diff_oss_key else None)

        name_a = img_a.original_name if img_a else "—"
        name_b = img_b.original_name if img_b else "—"
        score_txt = f"{score*100:.1f}%" if score is not None else "—"
        size_a = f"{img_a.width}×{img_a.height}" if img_a and img_a.width else "—"
        size_b = f"{img_b.width}×{img_b.height}" if img_b and img_b.width else "—"

        thumb_a_html = (f'<img class="thumb" src="{thumb_a_src}" alt="A" loading="lazy">'
                        if thumb_a_src else '<div class="thumb-placeholder">A</div>')
        thumb_b_html = (f'<img class="thumb" src="{thumb_b_src}" alt="B" loading="lazy">'
                        if thumb_b_src else '<div class="thumb-placeholder">B</div>')

        full_a_html = (f'<img class="full-img" src="{full_a_src}" alt="A">'
                       if full_a_src else '<div class="img-placeholder">暂无图片</div>')
        full_b_html = (f'<img class="full-img" src="{full_b_src}" alt="B">'
                       if full_b_src else '<div class="img-placeholder">暂无图片</div>')
        diff_html   = (f'<img class="full-img" src="{diff_src}" alt="差异图">'
                       if diff_src else '<div class="img-placeholder">暂无差异图</div>')

        pairs_html += f"""
        <div class="pair-row" onclick="toggleDetail(this)">
          <div class="pair-badge">{badge}</div>
          <div class="pair-info">
            <span class="pair-no">#{i+1}</span>
            <div class="pair-names">
              <span class="name-a" title="{name_a}">{name_a}</span>
              <span class="arrow">↔</span>
              <span class="name-b" title="{name_b}">{name_b}</span>
            </div>
          </div>
          <div class="pair-thumbs">
            {thumb_a_html}
            {thumb_b_html}
          </div>
          <div class="pair-score">{score_txt}</div>
        </div>
        <div class="pair-detail">
          <div class="detail-meta">
            <span class="detail-score-label">相似度：</span>
            <span class="detail-score-val {'detail-score-bad' if score is not None and score < 0.75 else ''}">{score_txt}</span>
            <span class="dim">{f"· 尺寸 A: {size_a}  B: {size_b}" if size_a != "—" else ""}</span>
          </div>
          <div class="detail-header">
            <div class="detail-col-label">
              <span class="tag tag-a">A</span>
              <span>{name_a}</span>
              <span class="dim">{size_a}</span>
            </div>
            <div class="detail-col-label">
              <span class="tag tag-b">B</span>
              <span>{name_b}</span>
              <span class="dim">{size_b}</span>
            </div>
          </div>
          <div class="detail-images detail-images-2col">
            <div class="detail-img-wrap">{full_a_html}</div>
            <div class="detail-img-wrap">{full_b_html}</div>
          </div>
        </div>
        """

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    algo_labels = {
        "balanced":   "标准模式",
        "document":   "文档对比",
        "structural": "结构探测",
        "pixel_exact":"像素对比",
    }
    pair_labels = {"sequential": "顺序配对", "prefix": "前缀配对"}

    oversized_banner = ""
    if use_url:
        oversized_banner = f"""
        <div class="banner-warn">
          ⚠ 报告图片总大小超过 50MB（估算 {estimated//1024//1024}MB），图片改用 URL 加载模式，
          需要连接到 MinIO 服务（localhost:13012）才能正常显示。
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>对比报告 — {task.name}</title>
<style>
  :root {{
    --green: #16a34a; --red: #dc2626; --amber: #d97706; --gray: #6b7280;
    --bg: #f8fafc; --card: #ffffff; --border: #e2e8f0;
    --primary: #0891b2; --text: #1e293b; --muted: #64748b;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         background: var(--bg); color: var(--text); line-height: 1.5; }}
  .container {{ max-width: 960px; margin: 0 auto; padding: 24px 16px 48px; }}

  /* 头部 */
  .header {{ background: var(--card); border: 1px solid var(--border);
             border-radius: 12px; padding: 20px 24px; margin-bottom: 16px; }}
  .header h1 {{ font-size: 20px; font-weight: 700; color: var(--text); }}
  .header .meta {{ display: flex; gap: 20px; flex-wrap: wrap; margin-top: 8px;
                   font-size: 13px; color: var(--muted); }}
  .header .meta span b {{ color: var(--text); }}

  /* 警告横幅 */
  .banner-warn {{ background: #fffbeb; border: 1px solid #fcd34d;
                  border-radius: 8px; padding: 10px 16px; margin-bottom: 16px;
                  font-size: 13px; color: #92400e; }}

  /* 统计栏 */
  .stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px; }}
  .stat {{ background: var(--card); border: 1px solid var(--border);
           border-radius: 10px; padding: 14px 16px; text-align: center; }}
  .stat .num {{ font-size: 22px; font-weight: 700; }}
  .stat .lbl {{ font-size: 12px; color: var(--muted); margin-top: 2px; }}
  .stat.green .num {{ color: var(--green); }}
  .stat.red   .num {{ color: var(--red); }}
  .stat.amber .num {{ color: var(--amber); }}

  /* 配对列表 */
  .list {{ background: var(--card); border: 1px solid var(--border);
           border-radius: 12px; overflow: hidden; }}
  .list-header {{ display: grid;
                  grid-template-columns: 90px 1fr 120px 64px;
                  gap: 12px; padding: 10px 16px;
                  font-size: 12px; font-weight: 600; color: var(--muted);
                  background: #f1f5f9; border-bottom: 1px solid var(--border); }}

  .pair-row {{ display: grid;
               grid-template-columns: 90px 1fr 120px 64px;
               gap: 12px; align-items: center;
               padding: 10px 16px; cursor: pointer;
               border-bottom: 1px solid var(--border);
               transition: background .15s; }}
  .pair-row:hover {{ background: #f8fafc; }}
  .pair-row.open  {{ background: #f0f9ff; }}

  .pair-badge {{ display: flex; justify-content: center; }}
  .badge {{ display: inline-flex; align-items: center; gap: 4px;
            font-size: 12px; font-weight: 600; padding: 3px 10px;
            border-radius: 99px; border: 1px solid; white-space: nowrap; }}
  .badge.similar   {{ color: var(--green); border-color: #bbf7d0; background: #f0fdf4; }}
  .badge.different {{ color: var(--red);   border-color: #fecaca; background: #fef2f2; }}
  .badge.warning   {{ color: var(--amber); border-color: #fde68a; background: #fffbeb; }}
  .badge.pending   {{ color: var(--gray);  border-color: #e5e7eb; background: #f9fafb; }}

  .pair-info {{ min-width: 0; }}
  .pair-no   {{ font-size: 11px; font-weight: 700; color: var(--muted); }}
  .pair-names {{ display: flex; align-items: center; gap: 6px; margin-top: 2px; font-size: 12px; }}
  .name-a,.name-b {{ max-width: 180px; overflow: hidden; text-overflow: ellipsis;
                     white-space: nowrap; color: var(--text); }}
  .arrow  {{ color: #cbd5e1; flex-shrink: 0; }}

  .pair-thumbs {{ display: flex; gap: 6px; justify-content: flex-end; }}
  .thumb {{ width: 48px; height: 48px; object-fit: cover; border-radius: 6px;
            border: 1px solid var(--border); background: #f1f5f9; }}
  .thumb-placeholder {{ width: 48px; height: 48px; border-radius: 6px; border: 1px solid var(--border);
                        background: #f1f5f9; display: flex; align-items: center; justify-content: center;
                        font-size: 11px; color: var(--muted); }}

  .pair-score {{ font-size: 13px; font-weight: 600; text-align: center; color: var(--muted); }}

  /* 详情展开区 */
  .pair-detail {{ display: none; padding: 16px; background: #f8fafc;
                  border-bottom: 1px solid var(--border); }}
  .pair-detail.open {{ display: block; }}

  /* 相似度信息行 */
  .detail-meta {{ display: flex; align-items: center; gap: 8px; margin-bottom: 12px;
                  font-size: 13px; }}
  .detail-score-label {{ color: var(--muted); }}
  .detail-score-val {{ font-weight: 700; font-size: 15px; color: var(--green); }}
  .detail-score-val.detail-score-bad {{ color: var(--red); }}

  .detail-header {{ display: grid; grid-template-columns: 1fr 1fr;
                    gap: 12px; margin-bottom: 10px; }}
  .detail-col-label {{ display: flex; align-items: center; gap: 6px;
                       font-size: 12px; color: var(--muted); }}
  .detail-col-label span:nth-child(2) {{ font-weight: 600; color: var(--text);
                                         overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 160px; }}
  .dim {{ color: var(--muted); font-size: 11px; }}

  .tag {{ display: inline-block; font-size: 10px; font-weight: 700;
          padding: 2px 7px; border-radius: 4px; color: #fff; flex-shrink: 0; }}
  .tag-a {{ background: #0891b2; }}
  .tag-b {{ background: #7c3aed; }}

  .detail-images-2col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
  .detail-img-wrap {{ border-radius: 8px; overflow: hidden; background: #f1f5f9;
                      border: 1px solid var(--border); }}
  .full-img {{ width: 100%; height: auto; display: block; }}
  .img-placeholder {{ padding: 24px; text-align: center; font-size: 12px; color: var(--muted); }}

  /* 页脚 */
  .footer {{ text-align: center; font-size: 12px; color: var(--muted); margin-top: 24px; }}

  @media (max-width: 640px) {{
    .stats {{ grid-template-columns: repeat(2, 1fr); }}
    .list-header, .pair-row {{ grid-template-columns: 80px 1fr 90px 50px; }}
    .detail-header, .detail-images-2col {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>
<div class="container">

  <!-- 头部 -->
  <div class="header">
    <h1>{task.name}</h1>
    <div class="meta">
      <span>共 <b>{pair_count}</b> 对图片</span>
      <span>配对方式：<b>{pair_labels.get(task.pair_mode, task.pair_mode)}</b></span>
      <span>对比算法：<b>{algo_labels.get(task.diff_algo, task.diff_algo)}</b></span>
      <span>生成时间：<b>{now}</b></span>
      {f'<span>描述：<b>{task.description}</b></span>' if task.description else ''}
    </div>
  </div>

  {oversized_banner}

  <!-- 统计 -->
  <div class="stats" id="stats-bar">
    <!-- 由 JS 动态填充 -->
  </div>

  <!-- 列表 -->
  <div class="list">
    <div class="list-header">
      <span>状态</span>
      <span>图片文件</span>
      <span style="text-align:right">缩略图</span>
      <span style="text-align:center">相似度</span>
    </div>
    {pairs_html}
  </div>

  <div class="footer">图片对比平台 · 自动生成报告 · {now}</div>
</div>

<script>
  function toggleDetail(row) {{
    var detail = row.nextElementSibling;
    var open = detail.classList.toggle('open');
    row.classList.toggle('open', open);
  }}

  // 动态统计
  (function() {{
    var badges = document.querySelectorAll('.badge');
    var cnt = {{similar:0, different:0, warning:0, pending:0}};
    badges.forEach(function(b) {{
      if (b.classList.contains('similar'))   cnt.similar++;
      else if (b.classList.contains('different')) cnt.different++;
      else if (b.classList.contains('warning'))   cnt.warning++;
      else cnt.pending++;
    }});
    var total = badges.length;
    document.getElementById('stats-bar').innerHTML =
      '<div class="stat"><div class="num">' + total + '</div><div class="lbl">总配对数</div></div>' +
      '<div class="stat green"><div class="num">' + cnt.similar + '</div><div class="lbl">正常</div></div>' +
      '<div class="stat red"><div class="num">' + cnt.different + '</div><div class="lbl">异常</div></div>' +
      '<div class="stat amber"><div class="num">' + (cnt.warning + cnt.pending) + '</div><div class="lbl">待计算/异常</div></div>';
  }})();
</script>
</body>
</html>"""

    return html.encode("utf-8"), use_url
