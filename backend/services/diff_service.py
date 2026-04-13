"""
差异计算服务
- 多指标融合相似度：像素差异率（主）× SSIM × HSV直方图（加权几何平均）
- 像素差分 + Otsu 二值化 + 形态学膨胀 + OpenCV 轮廓 bounding box 标注
- 尺寸对齐策略（resize / feature）
- 增量计算（已有 diff_results 记录则跳过）
- 配对模式：sequential（顺序）| prefix（文件名前缀匹配）
"""
import logging
import re
import uuid
import os
import sys
from datetime import datetime
from typing import Optional

import cv2
import numpy as np
from skimage.metrics import structural_similarity as ssim
from sqlalchemy.orm import Session

# ── 独立差异计算日志：按日期滚动写文件 + 同时打印到 stderr ──────────────────
_LOG_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "logs"
))

def diff_log(msg: str) -> None:
    """写差异计算日志：按日期滚动，logs/diff.YYYY-MM-DD.log，维护 diff.log 软链"""
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    log_path = os.path.join(_LOG_DIR, f"diff.{today}.log")
    line = f"{now.strftime('%Y-%m-%d %H:%M:%S')} [DIFF] {msg}\n"
    # 1. 写文件（按日期滚动，append）
    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
        # 维护 diff.log 软链，方便 tail -f logs/diff.log（仅 Unix/macOS）
        symlink = os.path.join(_LOG_DIR, "diff.log")
        try:
            target = f"diff.{today}.log"
            if os.path.islink(symlink):
                if os.readlink(symlink) != target:
                    os.remove(symlink)
                    os.symlink(target, symlink)
            elif not os.path.exists(symlink):
                os.symlink(target, symlink)
        except OSError:
            pass
    except Exception:
        pass
    # 2. 同时打印到 stderr（uvicorn 不吞 stderr）
    sys.stderr.write(line)
    sys.stderr.flush()

from models import Image, DiffResult, Task
from services.oss_service import client as minio_client, BUCKET, upload_bytes_to_oss, get_public_url

# 尺寸差异阈值
WARN_RATIO_THRESHOLD  = 0.10   # > 10%: size_warning = True
FORCE_RATIO_THRESHOLD = 0.30   # > 30%: 尝试特征配准

# ── 四种对比算法模式 ─────────────────────────────────────────────────────────
# 每种模式包含：权重、插值方式、diff阈值、掩码梯度阈值、是否使用掩码
ALGO_CONFIG: dict[str, dict] = {
    "balanced": {
        # 标准模式：通用场景，兼顾像素差异与结构相似性
        "weights":        {"diff": 0.40, "grid": 0.40, "ssim": 0.10, "hist": 0.10},
        "interp":         cv2.INTER_AREA,
        "diff_threshold": 15,    # 容忍 JPEG 压缩噪声
        "lap_threshold":  8,
        "use_mask":       True,
        "grid_size":      8,
        "worst_frac":     1/3,
    },
    "document": {
        # 文档对比模式：严格对比，适合 PDF/PNG 文档导出，能检测 DPI 差异和渲染细节
        "weights":        {"diff": 0.45, "grid": 0.45, "ssim": 0.10, "hist": 0.00},
        "interp":         cv2.INTER_LANCZOS4,  # 更精准的字体边缘保留
        "diff_threshold": 5,     # 严格，PNG 无 JPEG 噪声
        "lap_threshold":  4,     # 更敏感，检测细线差异
        "use_mask":       True,
        "grid_size":      8,
        "worst_frac":     1/3,
    },
    "structural": {
        # 结构探测模式：聚焦页面布局和元素增删，使用 4×4 大分块感知宏观结构变化
        "weights":        {"diff": 0.20, "grid": 0.60, "ssim": 0.15, "hist": 0.05},
        "interp":         cv2.INTER_AREA,
        "diff_threshold": 20,    # 宽松，只关注明显差异
        "lap_threshold":  12,    # 只检测强边缘（轮廓/框线）
        "use_mask":       True,
        "grid_size":      4,     # 4×4 大格子，感知整块区域变化
        "worst_frac":     1/4,
    },
    "pixel_exact": {
        # 像素级精确对比：全图逐像素，极严格，不容忍任何差异（含 DPI 变化）
        "weights":        {"diff": 0.70, "grid": 0.20, "ssim": 0.10, "hist": 0.00},
        "interp":         cv2.INTER_LANCZOS4,
        "diff_threshold": 3,     # 极严格，几乎不容忍任何差异
        "lap_threshold":  0,     # 不用掩码，全图参与
        "use_mask":       False, # 全图每个像素都参与计算
        "grid_size":      8,
        "worst_frac":     1/3,
    },
}

DEFAULT_ALGO = "balanced"
VALID_ALGOS  = set(ALGO_CONFIG.keys())

# 相似度判定阈值：低于此值认为差异显著（前端可高亮提示）
SIMILARITY_THRESHOLD = 0.75


# ─────────────────────────────────────────────
# 前缀提取
# ─────────────────────────────────────────────

def extract_prefix(filename: str) -> Optional[str]:
    """
    从文件名提取前缀。
    规则：去掉扩展名后，取最后一个 _A 或 _B 之前的部分。
    例：
      "homepage_A.png"  → "homepage"
      "login_v2_B.jpg"  → "login_v2"
      "test_a.png"      → "test"   （大小写不敏感）
      "nomark.png"      → None     （无法识别）
    """
    stem = filename.rsplit(".", 1)[0]
    m = re.match(r"^(.+)_([aAbB])$", stem)
    if m:
        return m.group(1)
    return None


def build_prefix_pairs(
    images_a: list[Image],
    images_b: list[Image],
) -> list[tuple[Optional[Image], Optional[Image], str]]:
    """
    按文件名前缀匹配 A 组和 B 组图片，返回配对列表。
    每项：(img_a, img_b, prefix_key)
    """
    map_a: dict[str, Image] = {}
    map_b: dict[str, Image] = {}
    unmatched_a: list[Image] = []
    unmatched_b: list[Image] = []

    for img in sorted(images_a, key=lambda x: x.sort_order):
        prefix = extract_prefix(img.original_name)
        if prefix is not None:
            map_a.setdefault(prefix, img)
        else:
            unmatched_a.append(img)

    for img in sorted(images_b, key=lambda x: x.sort_order):
        prefix = extract_prefix(img.original_name)
        if prefix is not None:
            map_b.setdefault(prefix, img)
        else:
            unmatched_b.append(img)

    all_keys = sorted(set(map_a.keys()) | set(map_b.keys()))
    pairs: list[tuple[Optional[Image], Optional[Image], str]] = [
        (map_a.get(k), map_b.get(k), k) for k in all_keys
    ]

    extra_count = max(len(unmatched_a), len(unmatched_b))
    for i in range(extra_count):
        img_a = unmatched_a[i] if i < len(unmatched_a) else None
        img_b = unmatched_b[i] if i < len(unmatched_b) else None
        pairs.append((img_a, img_b, f"__unmatched_{i}"))

    return pairs


# ─────────────────────────────────────────────
# 图片获取
# ─────────────────────────────────────────────

def _download_image(oss_key: str) -> Optional[np.ndarray]:
    """从 MinIO 下载图片到内存，返回 BGR ndarray"""
    try:
        response = minio_client.get_object(BUCKET, oss_key)
        data = response.read()
        response.close()
        arr = np.frombuffer(data, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        return img
    except Exception:
        return None


# ─────────────────────────────────────────────
# 尺寸对齐
# ─────────────────────────────────────────────

def _aspect_ratio_diff(a: np.ndarray, b: np.ndarray) -> float:
    """计算两张图宽高比的相对差值（0~1）"""
    ra = a.shape[1] / a.shape[0]
    rb = b.shape[1] / b.shape[0]
    return abs(ra - rb) / max(ra, rb)


def _align_resize(a: np.ndarray, b: np.ndarray,
                  interp: int = cv2.INTER_AREA) -> np.ndarray:
    """将 b 缩放到与 a 相同尺寸"""
    h, w = a.shape[:2]
    return cv2.resize(b, (w, h), interpolation=interp)


def _align_feature(a: np.ndarray, b: np.ndarray) -> Optional[np.ndarray]:
    """ORB 特征点配准，失败时返回 None（降级为 resize）"""
    try:
        orb = cv2.ORB_create(5000)
        kp_a, des_a = orb.detectAndCompute(a, None)
        kp_b, des_b = orb.detectAndCompute(b, None)
        if des_a is None or des_b is None or len(kp_a) < 4 or len(kp_b) < 4:
            return None
        matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        matches = sorted(matcher.match(des_a, des_b), key=lambda x: x.distance)
        if len(matches) < 4:
            return None
        matches = matches[:min(50, len(matches))]
        pts_a = np.float32([kp_a[m.queryIdx].pt for m in matches])
        pts_b = np.float32([kp_b[m.trainIdx].pt for m in matches])
        H, mask = cv2.findHomography(pts_b, pts_a, cv2.RANSAC, 5.0)
        if H is None:
            return None
        return cv2.warpPerspective(b, H, (a.shape[1], a.shape[0]))
    except Exception:
        return None


def align_images(a: np.ndarray, b: np.ndarray,
                 interp: int = cv2.INTER_AREA) -> tuple[np.ndarray, str, bool]:
    """
    对齐策略：
    - 差异 < 10%: resize，size_warning=False
    - 差异 10~30%: resize，size_warning=True
    - 差异 > 30%: 先尝试 feature 配准，失败则 resize，size_warning=True
    返回 (aligned_b, align_method, size_warning)
    """
    ratio_diff = _aspect_ratio_diff(a, b)
    size_warning = ratio_diff >= WARN_RATIO_THRESHOLD

    if ratio_diff > FORCE_RATIO_THRESHOLD:
        aligned = _align_feature(a, b)
        if aligned is not None:
            return aligned, "feature", size_warning
        return _align_resize(a, b, interp), "resize", size_warning

    return _align_resize(a, b, interp), "resize", size_warning


# ─────────────────────────────────────────────
# 差异计算核心（信息区掩码 + 四指标融合）
# ─────────────────────────────────────────────

def _info_mask(gray: np.ndarray, gradient_threshold: int = 8) -> np.ndarray:
    """
    生成信息区掩码：用拉普拉斯梯度检测有内容的像素区域。
    有内容（文字/图标/线条）→ 梯度大 → 纳入信息区
    空白背景 → 梯度小 → 排除
    膨胀 7×7 核确保文字周围也被纳入，避免边缘被漏掉。
    """
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    mag = np.abs(lap)
    mask = (mag > gradient_threshold).astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    return cv2.dilate(mask, kernel)


def _masked_diff_ratio(gray_a: np.ndarray, gray_b: np.ndarray,
                        mask: np.ndarray, noise_threshold: int = 15) -> float:
    """
    信息区差异像素面积比相似度（主力指标）。
    只在信息区像素中统计"有多少比例发生了变化"。
    noise_threshold=15：忽略 JPEG 压缩等轻微噪声（15/255 ≈ 6%）。

    全图方案 vs 掩码方案对比（手机截图，信息区 5.4%）：
      全图：差异率 4.3% → similarity 0.957（虚高）
      掩码：差异率 32%  → similarity 0.680（合理）
    """
    diff = cv2.absdiff(gray_a, gray_b)
    info_pixels = mask > 0
    total = float(info_pixels.sum())
    if total < 1:
        # 信息区为空（纯色图）→ 退化为全图方案
        total = float(gray_a.size)
        changed = float((diff > noise_threshold).sum())
    else:
        changed = float(((diff > noise_threshold) & info_pixels).sum())
    return float(1.0 - changed / total)


def _masked_grid_ssim(gray_a: np.ndarray, gray_b: np.ndarray,
                       mask: np.ndarray, grid: int = 8,
                       worst_frac: float = 1 / 3,
                       min_info_ratio: float = 0.10) -> float:
    """
    信息区感知的 8×8 分块 SSIM。
    跳过信息区像素占比 < min_info_ratio（默认 10%）的空白格子，
    只对有内容的格子计算 SSIM，取最差 worst_frac（1/3）块的均值。

    8×8=64 块，跳过空白后通常只剩 10~20 个有效块，
    最差 1/3 ≈ 4~7 块，精确反映内容实际变化区域。
    """
    h, w = gray_a.shape
    scores: list[float] = []
    for i in range(grid):
        for j in range(grid):
            r1, r2 = i * h // grid, (i + 1) * h // grid
            c1, c2 = j * w // grid, (j + 1) * w // grid
            ba = gray_a[r1:r2, c1:c2]
            bb = gray_b[r1:r2, c1:c2]
            bm = mask[r1:r2, c1:c2]
            if ba.size < 4:
                continue
            info_ratio = float((bm > 0).sum()) / bm.size
            if info_ratio < min_info_ratio:
                continue   # 跳过空白格子
            try:
                s, _ = ssim(ba, bb, full=True)
                scores.append(float(max(0.0, s)))
            except Exception:
                pass
    if not scores:
        # 没有有效块（全部空白）→ 退化为全图 4×4 分块
        return _fallback_grid_ssim(gray_a, gray_b)
    scores.sort()
    n = max(1, int(len(scores) * worst_frac))
    return float(np.mean(scores[:n]))


def _fallback_grid_ssim(gray_a: np.ndarray, gray_b: np.ndarray,
                         grid: int = 4, worst_frac: float = 0.25) -> float:
    """退化方案：全图 4×4 分块 SSIM（当掩码方案无效块时使用）"""
    h, w = gray_a.shape
    scores: list[float] = []
    for i in range(grid):
        for j in range(grid):
            r1, r2 = i * h // grid, (i + 1) * h // grid
            c1, c2 = j * w // grid, (j + 1) * w // grid
            ba, bb = gray_a[r1:r2, c1:c2], gray_b[r1:r2, c1:c2]
            if ba.size < 4:
                continue
            try:
                s, _ = ssim(ba, bb, full=True)
                scores.append(float(max(0.0, s)))
            except Exception:
                pass
    if not scores:
        return 1.0
    scores.sort()
    n = max(1, int(len(scores) * worst_frac))
    return float(np.mean(scores[:n]))


def _histogram_similarity(img_a: np.ndarray, img_b: np.ndarray) -> float:
    """HSV 直方图相似度（Bhattacharyya 距离，颜色主题变化感知）"""
    hsv_a = cv2.cvtColor(img_a, cv2.COLOR_BGR2HSV)
    hsv_b = cv2.cvtColor(img_b, cv2.COLOR_BGR2HSV)
    hist_a = cv2.calcHist([hsv_a], [0, 1], None, [50, 60], [0, 180, 0, 256])
    hist_b = cv2.calcHist([hsv_b], [0, 1], None, [50, 60], [0, 180, 0, 256])
    cv2.normalize(hist_a, hist_a, alpha=1, norm_type=cv2.NORM_L1)
    cv2.normalize(hist_b, hist_b, alpha=1, norm_type=cv2.NORM_L1)
    dist = cv2.compareHist(hist_a, hist_b, cv2.HISTCMP_BHATTACHARYYA)
    return float(max(0.0, 1.0 - dist))


def compute_diff(
    img_a: np.ndarray,
    img_b_aligned: np.ndarray,
    pair_label: str = "?",
    algo: str = DEFAULT_ALGO,
) -> tuple[float, np.ndarray]:
    """
    根据 algo 模式计算相似度 + 差异区域标注。
    四种模式：balanced / document / structural / pixel_exact
    返回 (score: 0~1, annotated_img_bgr)
    """
    cfg = ALGO_CONFIG.get(algo, ALGO_CONFIG[DEFAULT_ALGO])
    weights        = cfg["weights"]
    diff_threshold = cfg["diff_threshold"]
    lap_threshold  = cfg["lap_threshold"]
    use_mask       = cfg["use_mask"]
    grid_size      = cfg["grid_size"]
    worst_frac     = cfg["worst_frac"]

    gray_a = cv2.cvtColor(img_a,         cv2.COLOR_BGR2GRAY)
    gray_b = cv2.cvtColor(img_b_aligned, cv2.COLOR_BGR2GRAY)

    # ── 掩码（pixel_exact 全图，其余用信息区掩码）────────────────────────────
    if use_mask:
        mask     = _info_mask(gray_a, gradient_threshold=lap_threshold)
        info_pct = float((mask > 0).sum()) / mask.size * 100
    else:
        mask     = np.ones_like(gray_a, dtype=np.uint8) * 255
        info_pct = 100.0

    # ── 各指标计算 ────────────────────────────────────────────────────────────
    diff_val  = _masked_diff_ratio(gray_a, gray_b, mask, noise_threshold=diff_threshold)
    grid_val  = _masked_grid_ssim(gray_a, gray_b, mask, grid=grid_size, worst_frac=worst_frac)
    ssim_val, diff_map = ssim(gray_a, gray_b, full=True)
    ssim_val  = float(max(0.0, ssim_val))
    hist_val  = _histogram_similarity(img_a, img_b_aligned)

    # ── 加权几何平均融合 ──────────────────────────────────────────────────────
    eps = 1e-9
    score = 1.0
    for k, w_val in weights.items():
        if w_val <= 0:
            continue
        v = {"diff": diff_val, "grid": grid_val, "ssim": ssim_val, "hist": hist_val}[k]
        score *= (v + eps) ** w_val
    score = float(min(1.0, max(0.0, score)))

    # ── 日志 ─────────────────────────────────────────────────────────────────
    tag = "[相似]" if score >= SIMILARITY_THRESHOLD else "[差异显著]"
    diff_log(
        f"pair={pair_label:<26}  algo={algo:<12}  info={info_pct:.1f}%"
        f"  diff={diff_val:.4f}(thr={diff_threshold})"
        f"  grid={grid_val:.4f}(g{grid_size})"
        f"  ssim={ssim_val:.4f}"
        f"  hist={hist_val:.4f}"
        f"  => {score*100:.1f}%  {tag}"
    )

    # ── 差异区域标注 ──────────────────────────────────────────────────────────
    diff_uint8 = (diff_map * 255).astype(np.uint8)
    _, thresh = cv2.threshold(
        diff_uint8, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU
    )
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    thresh = cv2.dilate(thresh, kernel, iterations=1)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    result_img = img_a.copy()
    for c in contours:
        if cv2.contourArea(c) < 100:
            continue
        x, y, w_c, h_c = cv2.boundingRect(c)
        cv2.rectangle(result_img, (x, y), (x + w_c, y + h_c), (0, 0, 255), 2)

    return score, result_img


# ─────────────────────────────────────────────
# 增量触发入口
# ─────────────────────────────────────────────

def run_diff_for_new_pairs(task_id: int) -> None:
    """
    BackgroundTasks 入口：遍历任务所有配对，跳过已有缓存，计算新配对差异。
    注意：此函数在后台线程中运行，需要自己创建 DB Session。
    """
    from database import SessionLocal
    db = SessionLocal()
    try:
        _run_diff_internal(db, task_id)
    finally:
        db.close()


def _run_diff_internal(db: Session, task_id: int) -> None:
    import datetime

    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return

    task.status = "active"
    task.updated_at = datetime.datetime.utcnow()
    db.commit()

    images_a = (
        db.query(Image)
        .filter(Image.task_id == task_id, Image.group == "A")
        .order_by(Image.sort_order)
        .all()
    )
    images_b = (
        db.query(Image)
        .filter(Image.task_id == task_id, Image.group == "B")
        .order_by(Image.sort_order)
        .all()
    )

    # 根据 pair_mode 生成配对列表
    if task.pair_mode == "prefix":
        raw_pairs = build_prefix_pairs(images_a, images_b)
        pairs = [(img_a, img_b) for img_a, img_b, _ in raw_pairs]
    else:
        pair_count = max(len(images_a), len(images_b))
        pairs = [
            (
                images_a[i] if i < len(images_a) else None,
                images_b[i] if i < len(images_b) else None,
            )
            for i in range(pair_count)
        ]

    for pair_index, (img_a, img_b) in enumerate(pairs):
        if not img_a or not img_b:
            continue

        existing = (
            db.query(DiffResult)
            .filter(
                DiffResult.image_a_id == img_a.id,
                DiffResult.image_b_id == img_b.id,
            )
            .first()
        )
        if existing and existing.status == "done":
            continue

        if existing:
            diff_record = existing
            # 修正 pair_index（旧记录可能因算法变更而 pair_index 不正确）
            if diff_record.pair_index != pair_index:
                diff_record.pair_index = pair_index
        else:
            diff_record = DiffResult(
                task_id=task_id,
                image_a_id=img_a.id,
                image_b_id=img_b.id,
                pair_index=pair_index,
            )
            db.add(diff_record)
        diff_record.status = "running"
        db.commit()

        try:
            task_algo = getattr(task, "diff_algo", DEFAULT_ALGO) or DEFAULT_ALGO
            _compute_pair(db, diff_record, img_a, img_b, algo=task_algo)
        except Exception:
            diff_record.status = "failed"
            db.commit()

    pending = (
        db.query(DiffResult)
        .filter(
            DiffResult.task_id == task_id,
            DiffResult.status.in_(["pending", "running"]),
        )
        .count()
    )
    if pending == 0:
        task.status = "completed"
        task.updated_at = datetime.datetime.utcnow()
        db.commit()


def _compute_pair(
    db: Session,
    diff_record: DiffResult,
    img_a: Image,
    img_b: Image,
    algo: str = DEFAULT_ALGO,
) -> None:
    """计算单对图片差异，结果写入 diff_record"""
    arr_a = _download_image(img_a.oss_key)
    arr_b = _download_image(img_b.oss_key)

    if arr_a is None or arr_b is None:
        raise ValueError("无法从 MinIO 获取图片")

    # 根据算法模式选择插值方式
    cfg    = ALGO_CONFIG.get(algo, ALGO_CONFIG[DEFAULT_ALGO])
    interp = cfg["interp"]

    arr_b_aligned, align_method, size_warning = align_images(arr_a, arr_b, interp=interp)

    pair_label = f"a={img_a.id}({img_a.original_name[:12]}) b={img_b.id}({img_b.original_name[:12]})"
    diff_log(f"开始计算: task={diff_record.task_id} pair_index={diff_record.pair_index} "
             f"algo={algo} align={align_method} size_warning={size_warning}  [{pair_label}]")

    score, annotated = compute_diff(arr_a, arr_b_aligned, pair_label=pair_label, algo=algo)

    _, buf = cv2.imencode(".png", annotated)
    diff_bytes = buf.tobytes()

    diff_oss_key = f"diffs/{uuid.uuid4().hex}_diff.png"
    upload_bytes_to_oss(diff_bytes, diff_oss_key, content_type="image/png")
    diff_log(f"完成: task={diff_record.task_id} pair_index={diff_record.pair_index} "
             f"score={score:.4f} ({score*100:.1f}%) diff_key={diff_oss_key}")

    diff_record.diff_oss_key  = diff_oss_key
    diff_record.diff_score    = score
    diff_record.align_method  = align_method
    diff_record.size_warning  = size_warning
    diff_record.status        = "done"
    db.commit()


# ─────────────────────────────────────────────
# 查询辅助
# ─────────────────────────────────────────────

def get_diff_status(db: Session, task_id: int) -> dict:
    from sqlalchemy import func

    counts = (
        db.query(DiffResult.status, func.count(DiffResult.id))
        .filter(DiffResult.task_id == task_id)
        .group_by(DiffResult.status)
        .all()
    )
    status_map = {s: c for s, c in counts}
    total = sum(status_map.values())
    return {
        "task_id": task_id,
        "total": total,
        "done":    status_map.get("done", 0),
        "running": status_map.get("running", 0),
        "pending": status_map.get("pending", 0),
        "failed":  status_map.get("failed", 0),
    }


def get_diff_pair(db: Session, task_id: int, pair_index: int) -> Optional[DiffResult]:
    return (
        db.query(DiffResult)
        .filter(DiffResult.task_id == task_id, DiffResult.pair_index == pair_index)
        .first()
    )
