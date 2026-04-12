"""
test_algo.py — 对比算法独立测试（聚焦相同场景内容变化）
================================================
直接用 Python 运行，不依赖数据库/MinIO/pytest。

新算法核心：
    diff_ratio^0.45 × grid_8x8^0.35 × ssim^0.10 × hist^0.10

    diff_ratio：差异像素面积占比，对局部文字/图标替换灵敏度高3~5倍
    grid_8x8：8×8分块SSIM最差1/3，精确定位局部变化区域
    ssim：全局结构辅助，低权重避免虚高
    hist：颜色主题变化感知

运行方式（在 backend/ 目录下执行）：
    uv run python tests/test_algo.py              # 使用当前最优权重
    uv run python tests/test_algo.py --save-images # 同时保存对比图
"""

import sys, os, argparse, time
import cv2
import numpy as np
from skimage.metrics import structural_similarity as skimage_ssim

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

from services.diff_service import align_images, extract_prefix

# ─── 颜色输出 ─────────────────────────────────────────────────────────────────
RED = "\033[31m"; GREEN = "\033[32m"; YELLOW = "\033[33m"
CYAN = "\033[36m"; BOLD = "\033[1m"; DIM = "\033[2m"; NC = "\033[0m"

def cs(score, lo, hi):
    p = f"{score*100:.1f}%"
    ok = lo <= score <= hi
    if ok:   return f"{GREEN}{BOLD}{p}{NC}", True
    if score > hi: return f"{YELLOW}{p}{NC}", False   # 偏高
    return f"{RED}{p}{NC}", False                      # 偏低

def hr(c="─", w=68): print(DIM + c*w + NC)


# ─── 算法函数（聚焦相同场景内容变化）────────────────────────────────────────

def diff_pixel_ratio(ga: np.ndarray, gb: np.ndarray, threshold: int = 15) -> float:
    """
    差异像素【面积占比】相似度（主力指标）。
    统计"有多少比例的像素发生了变化"，对小区域文字/图标替换灵敏度高。
    threshold=15：忽略 JPEG 压缩噪声。
    """
    diff = cv2.absdiff(ga, gb)
    changed = float((diff > threshold).sum()) / diff.size
    return float(1.0 - changed)


def info_mask(gray: np.ndarray, lap_thresh: float = 8.0) -> np.ndarray:
    """
    信息区域掩码：用拉普拉斯梯度检测"有内容的像素"。
    空白背景梯度接近 0，文字/图标/边缘梯度高。
    先轻度模糊再计算，避免 JPEG 噪声把空白区误判为信息区。
    返回 bool 掩码，True = 有信息。
    """
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    lap = cv2.Laplacian(blurred.astype(np.float32), cv2.CV_32F)
    mask = np.abs(lap) > lap_thresh
    # 膨胀：把文字/图标周围的白边也纳入信息区（避免差异被空白稀释）
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    mask_dilated = cv2.dilate(mask.astype(np.uint8), kernel) > 0
    return mask_dilated


def masked_diff_ratio(ga: np.ndarray, gb: np.ndarray,
                      threshold: int = 15, lap_thresh: float = 8.0,
                      min_info_ratio: float = 0.05) -> float:
    """
    只在信息区域（文字/图标/边缘周围）内计算差异像素面积比。
    核心思路：空白背景完全一致，不应贡献相似度；
              只看"有内容的区域"里有多少比例发生了变化。
    
    min_info_ratio: 若信息区占比过低（<5%），降级为普通 diff_pixel_ratio
    """
    mask = info_mask(ga, lap_thresh)
    info_ratio = mask.sum() / mask.size
    
    # 信息区太少（近纯色图）→ 降级为全图计算
    if info_ratio < min_info_ratio:
        return diff_pixel_ratio(ga, gb, threshold)
    
    # 只取信息区像素
    diff = cv2.absdiff(ga, gb)
    diff_in_info = diff[mask]
    changed_ratio = float((diff_in_info > threshold).sum()) / len(diff_in_info)
    return float(1.0 - changed_ratio)


def masked_grid_ssim(ga: np.ndarray, gb: np.ndarray,
                     grid: int = 8, worst_frac: float = 1/3,
                     lap_thresh: float = 8.0,
                     min_info_ratio: float = 0.10) -> float:
    """
    分块 SSIM，跳过信息内容过少的空白块（背景/间距块）。
    空白块 SSIM 虚高（都是空白，当然相似），纳入最差区域排名会稀释真实差异。
    只统计信息区占比 >= min_info_ratio 的块。
    """
    h, w = ga.shape
    scores = []
    for i in range(grid):
        for j in range(grid):
            r1, r2 = i*h//grid, (i+1)*h//grid
            c1, c2 = j*w//grid, (j+1)*w//grid
            ba, bb = ga[r1:r2, c1:c2], gb[r1:r2, c1:c2]
            if ba.size < 4:
                continue
            # 检查此块的信息区占比
            mask_block = info_mask(ba, lap_thresh)
            if mask_block.sum() / mask_block.size < min_info_ratio:
                continue   # 空白块，跳过
            try:
                s, _ = skimage_ssim(ba, bb, full=True)
                scores.append(float(max(0.0, s)))
            except Exception:
                pass
    
    if not scores:
        # 全是空白块（如纯色图）→ 降级为全图 grid_ssim
        return grid_ssim(ga, gb, grid=grid, worst_frac=worst_frac)
    
    scores.sort()
    n = max(1, int(len(scores) * worst_frac))
    return float(np.mean(scores[:n]))


def grid_ssim(ga: np.ndarray, gb: np.ndarray, grid: int = 8, worst_frac: float = 1/3) -> float:
    """
    分块 SSIM（8×8=64块），取最差 1/3（约21块）均值。
    8×8 精度：每块约 50×37px，能精确捕捉单行文字变化。
    worst_frac=1/3：最差区域比全图更能反映内容实际变化。
    """
    h, w = ga.shape
    scores = []
    for i in range(grid):
        for j in range(grid):
            r1, r2 = i*h//grid, (i+1)*h//grid
            c1, c2 = j*w//grid, (j+1)*w//grid
            ba, bb = ga[r1:r2, c1:c2], gb[r1:r2, c1:c2]
            if ba.size < 4: continue
            try:
                s, _ = skimage_ssim(ba, bb, full=True)
                scores.append(float(max(0.0, s)))
            except Exception:
                pass
    if not scores: return 1.0
    scores.sort()
    n = max(1, int(len(scores) * worst_frac))
    return float(np.mean(scores[:n]))


def ssim_global(ga: np.ndarray, gb: np.ndarray):
    """全图 SSIM，返回 (score, diff_map)"""
    s, dm = skimage_ssim(ga, gb, full=True)
    return float(max(0.0, s)), dm


def hist_similarity(img_a: np.ndarray, img_b: np.ndarray) -> float:
    """HSV 直方图 Bhattacharyya 相似度（颜色主题感知）"""
    ha = cv2.cvtColor(img_a, cv2.COLOR_BGR2HSV)
    hb = cv2.cvtColor(img_b, cv2.COLOR_BGR2HSV)
    ha_h = cv2.calcHist([ha], [0, 1], None, [50, 60], [0, 180, 0, 256])
    hb_h = cv2.calcHist([hb], [0, 1], None, [50, 60], [0, 180, 0, 256])
    cv2.normalize(ha_h, ha_h, alpha=1, norm_type=cv2.NORM_L1)
    cv2.normalize(hb_h, hb_h, alpha=1, norm_type=cv2.NORM_L1)
    dist = cv2.compareHist(ha_h, hb_h, cv2.HISTCMP_BHATTACHARYYA)
    return float(max(0.0, 1.0 - dist))


def fuse(metrics: dict, weights: dict) -> float:
    """加权几何平均融合"""
    eps = 1e-9
    s = 1.0
    for k, w in weights.items():
        s *= (metrics.get(k, 1.0) + eps) ** w
    return float(min(1.0, max(0.0, s)))

# ─── 融合权重（两套方案对比）────────────────────────────────────────────────

# 方案A（原有：全图指标）
WEIGHTS_FULL = {
    "diff_ratio": 0.45,
    "grid":       0.35,
    "ssim":       0.10,
    "hist":       0.10,
}

# 方案B（新：信息区域掩码指标）
WEIGHTS_MASKED = {
    "m_diff":  0.50,   # masked_diff_ratio：只看有内容区域的差异面积
    "m_grid":  0.35,   # masked_grid_ssim：跳过空白块的分块SSIM
    "ssim":    0.05,   # 全局 SSIM（极低权重）
    "hist":    0.10,   # 颜色直方图
}

WEIGHTS = WEIGHTS_MASKED   # 当前使用方案

# ─── 文档专用权重（PNG 无损导出对比）──────────────────────────────────────────
# 文档特点：内容完全确定，PNG 无噪声，差异极小且规律；颜色变化不重要
WEIGHTS_DOC = {
    "m_diff": 0.55,   # 差异面积（主力，PNG 无噪声可信赖更高阈值灵敏度）
    "m_grid": 0.35,   # 分块结构
    "ssim":   0.10,   # 全局结构兜底
    "hist":   0.00,   # 文档通常黑白，颜色不重要
}


def doc_align(img_a: np.ndarray, img_b: np.ndarray) -> tuple[np.ndarray, str]:
    """
    文档模式对齐：优先使用 INTER_LANCZOS4 高质量插值。
    LANCZOS4：在缩放时对文字细线/边缘保留最好，最小化缩放引入的伪差异。
    当前后端默认用 INTER_AREA，对文字边缘模糊更多，会引入额外像素差异。
    """
    h, w = img_a.shape[:2]
    if img_b.shape[:2] == (h, w):
        return img_b.copy(), "none（尺寸相同）"
    b_resized = cv2.resize(img_b, (w, h), interpolation=cv2.INTER_LANCZOS4)
    return b_resized, f"lanczos4（{img_b.shape[1]}×{img_b.shape[0]}→{w}×{h}）"


def run_doc_real_dir(real_dir: str, save_dir: str = None):
    """
    文档模式：从目录读取图片，对每对图片同时运行「标准模式」和「文档模式」，
    并排展示差异，帮助判断哪种参数组合更准确。
    """
    EXTS = {".png", ".jpg", ".jpeg", ".webp"}
    files = sorted([f for f in os.listdir(real_dir)
                    if os.path.splitext(f.lower())[1] in EXTS])
    if not files:
        print(f"\n{RED}目录中没有找到图片文件{NC}"); return

    hr("═")
    print(f"{BOLD}【文档对比模式测试】{NC}  目录：{real_dir}")
    print(f"发现 {len(files)} 张图片")
    print(f"标准模式：INTER_AREA + thr=15 + lap=8  |  文档模式：LANCZOS4 + thr=5 + lap=4")
    hr("═")

    # 配对（同 run_real_dir）
    map_a, map_b, unmatched = {}, {}, []
    for fname in files:
        prefix = extract_prefix(fname)
        if prefix:
            stem_lower = os.path.splitext(fname)[0].lower()
            (map_a if stem_lower.endswith("_a") else map_b)[prefix] = fname
        else:
            unmatched.append(fname)

    pairs = [(map_a[k], map_b[k], k)
             for k in sorted(set(map_a) & set(map_b))]
    for i in range(0, len(unmatched) - 1, 2):
        pairs.append((unmatched[i], unmatched[i+1], f"pair_{i//2+1}"))

    if not pairs:
        print(f"{RED}没有找到有效配对{NC}"); return

    print(f"共 {len(pairs)} 对，开始测试...\n")

    summary = []
    for a_name, b_name, label in pairs:
        img_a = cv2.imread(os.path.join(real_dir, a_name))
        img_b = cv2.imread(os.path.join(real_dir, b_name))
        if img_a is None or img_b is None:
            print(f"  {RED}✘{NC}  无法读取: {a_name} / {b_name}"); continue

        print(f"{BOLD}▶ [{label}]{NC}")
        print(f"  A: {a_name}  ({img_a.shape[1]}×{img_a.shape[0]})")
        print(f"  B: {b_name}  ({img_b.shape[1]}×{img_b.shape[0]})")

        t0 = time.time()

        # ── 标准模式：INTER_AREA + thr=15 + lap=8 ─────────────────────────
        std_b, std_method, _ = align_images(img_a, img_b)
        ga   = cv2.cvtColor(img_a, cv2.COLOR_BGR2GRAY)
        gb_s = cv2.cvtColor(std_b, cv2.COLOR_BGR2GRAY)
        ssim_s, _ = ssim_global(ga, gb_s)
        m_std = {
            "m_diff": masked_diff_ratio(ga, gb_s, threshold=15, lap_thresh=8.0),
            "m_grid": masked_grid_ssim( ga, gb_s, lap_thresh=8.0),
            "ssim":   ssim_s,
            "hist":   hist_similarity(img_a, std_b),
        }
        score_std = fuse(m_std, WEIGHTS_MASKED)

        # ── 文档模式：LANCZOS4 + thr=5 + lap=4 ────────────────────────────
        doc_b, doc_method = doc_align(img_a, img_b)
        gb_d = cv2.cvtColor(doc_b, cv2.COLOR_BGR2GRAY)
        ssim_d, diff_map_d = ssim_global(ga, gb_d)
        m_doc = {
            "m_diff": masked_diff_ratio(ga, gb_d, threshold=5,  lap_thresh=4.0),
            "m_grid": masked_grid_ssim( ga, gb_d, lap_thresh=4.0),
            "ssim":   ssim_d,
            "hist":   hist_similarity(img_a, doc_b),
        }
        score_doc = fuse(m_doc, WEIGHTS_DOC)
        elapsed = int((time.time() - t0) * 1000)

        # ── 展示 ──────────────────────────────────────────────────────────
        def sc(s):
            p = f"{s*100:.1f}%"
            return (f"{GREEN}{BOLD}{p}{NC}" if s >= 0.90 else
                    f"{GREEN}{p}{NC}"       if s >= 0.75 else
                    f"{YELLOW}{p}{NC}"      if s >= 0.60 else
                    f"{RED}{p}{NC}")

        print(f"  对齐(标准): {CYAN}{std_method}{NC}")
        print(f"  对齐(文档): {CYAN}{doc_method}{NC}")
        print()
        print(f"  {'指标':<12}  {'标准(A:thr15,lap8)':>20}  {'文档(L:thr5,lap4)':>20}")
        hr("─", 60)
        rows_data = [
            ("差异面积",
             f"{m_std['m_diff']:.4f}",
             f"{m_doc['m_diff']:.4f}"),
            ("分块最差",
             f"{m_std['m_grid']:.4f}",
             f"{m_doc['m_grid']:.4f}"),
            ("全局SSIM",
             f"{m_std['ssim']:.4f}",
             f"{m_doc['ssim']:.4f}"),
            ("颜色直方图",
             f"{m_std['hist']:.4f}(w=0.10)",
             f"{m_doc['hist']:.4f}(w=0.00)"),
        ]
        for lbl, vs, vd in rows_data:
            print(f"  {lbl:<12}  {vs:>20}  {vd:>20}")
        hr("─", 60)
        delta = score_doc - score_std
        arr = (f"{GREEN}↑{abs(delta)*100:.1f}%{NC}" if delta >  0.005 else
               f"{RED}↓{abs(delta)*100:.1f}%{NC}"  if delta < -0.005 else "≈")
        print(f"  {'融合分数':<12}  {sc(score_std):>20}  {sc(score_doc):>20}  {arr}  ({elapsed}ms)")

        # ── 差异放大图 ────────────────────────────────────────────────────
        if save_dir:
            os.makedirs(save_dir, exist_ok=True)
            # 差异 ×5 放大（HOT 伪彩色，红=差异大）
            absdiff = cv2.absdiff(ga, gb_d)
            diff_x5 = cv2.applyColorMap(
                cv2.convertScaleAbs(absdiff, alpha=5.0),
                cv2.COLORMAP_HOT
            )
            sn = label.replace(" ", "_").replace("/", "-")
            cv2.imwrite(os.path.join(save_dir, f"doc_{sn}_A.png"),       img_a)
            cv2.imwrite(os.path.join(save_dir, f"doc_{sn}_B_lanczos.png"), doc_b)
            cv2.imwrite(os.path.join(save_dir, f"doc_{sn}_diff_x5.png"), diff_x5)
            print(f"  差异图（像素差×5，HOT彩色）→ doc_{sn}_diff_x5.png")

        print()
        summary.append((label, score_std, score_doc, delta))

    # 汇总
    hr("═")
    print(f"\n{BOLD}汇总{NC}\n")
    print(f"  {'配对':<28}  {'标准模式':>9}  {'文档模式':>9}  改善?")
    hr()
    for lbl, ss, sd, d in summary:
        def sc2(s):
            p = f"{s*100:.1f}%"
            return (f"{GREEN}{BOLD}{p}{NC}" if s >= 0.90 else
                    f"{GREEN}{p}{NC}"       if s >= 0.75 else
                    f"{YELLOW}{p}{NC}"      if s >= 0.60 else
                    f"{RED}{p}{NC}")
        arr = (f"{GREEN}↑{abs(d)*100:.1f}%{NC}" if d >  0.005 else
               f"{RED}↓{abs(d)*100:.1f}%{NC}"  if d < -0.005 else "≈")
        print(f"  {lbl:<28}  {sc2(ss):>9}  {sc2(sd):>9}  {arr}")
    hr("═")


# ─── 图片生成工厂 ─────────────────────────────────────────────────────────────

def solid(w, h, bgr):
    img = np.zeros((h, w, 3), dtype=np.uint8); img[:] = bgr; return img

def gradient_h(w, h):
    img = np.zeros((h, w, 3), dtype=np.uint8)
    for x in range(w):
        t = x/(w-1)
        img[:, x] = (int(255*(1-t)), 0, int(255*t))
    return img

def text_image(w, h, text, bg=(240,240,240), fg=(30,30,30)):
    img = np.full((h, w, 3), bg, dtype=np.uint8)
    sc = min(w,h)/200; th = max(1, int(sc*2))
    (tw, tth), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, sc, th)
    cv2.putText(img, text, ((w-tw)//2, (h+tth)//2),
                cv2.FONT_HERSHEY_SIMPLEX, sc, fg, th, cv2.LINE_AA)
    return img

def ui_page(w, h, title, lines):
    """模拟 UI 页面：顶栏 + 多行内容"""
    img = np.full((h, w, 3), (248,248,248), dtype=np.uint8)
    cv2.rectangle(img, (0,0), (w,56), (50,120,220), -1)
    cv2.putText(img, title, (16,38), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (255,255,255), 2)
    for i, line in enumerate(lines):
        y = 92 + i * 44
        cv2.rectangle(img, (12, y-20), (w-12, y+18), (255,255,255), -1)
        cv2.rectangle(img, (12, y-20), (w-12, y+18), (220,220,220), 1)
        cv2.putText(img, line, (20, y+4), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (60,60,60), 1)
    return img

def ui_with_icon(w, h, title, icon_color, label):
    """模拟含图标的 UI（测试图标颜色/形状变化）"""
    img = np.full((h, w, 3), (245,245,245), dtype=np.uint8)
    cv2.rectangle(img, (0,0), (w,55), (50,120,220), -1)
    cv2.putText(img, title, (16,38), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255), 2)
    for iy in [100, 160, 220]:
        cv2.circle(img, (40, iy), 18, icon_color, -1)
        cv2.rectangle(img, (68, iy-14), (w-16, iy+14), (220,220,220), -1)
        cv2.putText(img, label, (72, iy+5), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (60,60,60), 1)
    return img

def add_noise(img, sigma=5):
    np.random.seed(42)
    n = np.random.normal(0, sigma, img.shape).astype(np.int16)
    return np.clip(img.astype(np.int16)+n, 0, 255).astype(np.uint8)

def rotate(img, angle):
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w/2,h/2), angle, 1.0)
    return cv2.warpAffine(img, M, (w,h))


# ─── 测试用例集 ───────────────────────────────────────────────────────────────

def build_cases(W=400, H=300):
    cases = []
    W, H = 400, 300

    # ── A：完全相同（基线）──────────────────────────────────────────────────
    img = ui_page(W, H, "Account", ["Email: user@test.com", "Storage: 0MB/4GB", "Password: ******"])
    cases.append(("完全相同",
        img, img.copy(), (0.95, 1.00), "基线，必须接近 100%"))

    # ── B：噪声（同场景轻微抖动）──────────────────────────────────────────
    cases.append(("轻微噪声(σ=5)",
        img, add_noise(img, 5),
        (0.88, 1.00), "相机抖动/压缩噪声，应接近 100%"))
    cases.append(("中等噪声(σ=20)",
        img, add_noise(img, 20),
        (0.60, 0.88), "明显噪声干扰"))

    # ── C：核心场景——相同页面，内容变化 ─────────────────────────────────
    page_a = ui_page(W, H, "Account",
        ["Email: user@test.com", "Storage: 0MB / 4GB", "Password  >>"])
    page_b = ui_page(W, H, "Settings",
        ["Select service type:", "Email: user@test.com", "App Password  Get"])
    cases.append(("同布局-标题+内容均变",
        page_a, page_b, (0.40, 0.72), "标题+多行内容均换，差异大"))

    page_c = ui_page(W, H, "Account",
        ["Email: user@test.com", "Storage: 2.1GB / 4GB", "Password  >>"])
    cases.append(("同布局-仅数值变化",
        page_a, page_c, (0.78, 0.96), "只换了存储数值，差异很小"))

    page_d = ui_page(W, H, "Account",
        ["Email: newuser@example.com", "Storage: 0MB / 4GB", "Password  >>"])
    cases.append(("同布局-邮件地址变化",
        page_a, page_d, (0.65, 0.90), "一行内容被完全替换"))

    # ── D：图标变化 ────────────────────────────────────────────────────────
    icon_a = ui_with_icon(W, H, "Home", (80, 200, 80), "Active item")
    icon_b = ui_with_icon(W, H, "Home", (80, 80, 200), "Active item")
    cases.append(("图标颜色变化（布局同）",
        icon_a, icon_b, (0.55, 0.85), "同布局，图标颜色换了"))

    icon_c = ui_with_icon(W, H, "Settings", (200, 80, 80), "Inactive item")
    cases.append(("图标+标题+文字均变",
        icon_a, icon_c, (0.30, 0.68), "多处同时变化"))

    # ── E：颜色主题变化 ───────────────────────────────────────────────────
    cases.append(("纯色-蓝vs红",
        solid(W,H,(200,100,50)), solid(W,H,(50,100,200)),
        (0.00, 0.50), "完全不同的颜色"))

    # ── F：完全不相关 ─────────────────────────────────────────────────────
    cases.append(("文字-浅底vs深底",
        text_image(W,H,"Hello World", bg=(240,240,240), fg=(30,30,30)),
        text_image(W,H,"Bye World",   bg=(30,30,30),   fg=(240,240,240)),
        (0.00, 0.40), "内容+配色完全不同"))
    cases.append(("纯白vs纯黑",
        solid(W,H,(255,255,255)), solid(W,H,(0,0,0)),
        (0.00, 0.10), "极端对立"))

    # ── G：轻微位移/旋转 ─────────────────────────────────────────────────
    cases.append(("旋转 2°",
        page_a, rotate(page_a, 2),
        (0.80, 1.00), "轻微旋转（手持拍照）"))
    cases.append(("旋转 10°",
        page_a, rotate(page_a, 10),
        (0.55, 0.90), "明显旋转"))

    return cases


# ─── 单次 Case 运行 ───────────────────────────────────────────────────────────

def run_case(name, img_a, img_b, expect, note, weights, save_dir=None, verbose=True):
    t0 = time.time()
    img_b_a, align_method, size_warn = align_images(img_a, img_b)
    ga = cv2.cvtColor(img_a,   cv2.COLOR_BGR2GRAY)
    gb = cv2.cvtColor(img_b_a, cv2.COLOR_BGR2GRAY)

    ssim_val, diff_map = ssim_global(ga, gb)

    # ── 方案A：全图指标 ──────────────────────────────────────────────────
    metrics_full = {
        "diff_ratio": diff_pixel_ratio(ga, gb),
        "grid":       grid_ssim(ga, gb, grid=8, worst_frac=1/3),
        "ssim":       ssim_val,
        "hist":       hist_similarity(img_a, img_b_a),
    }
    score_full = fuse(metrics_full, WEIGHTS_FULL)

    # ── 方案B：信息区域掩码指标 ─────────────────────────────────────────
    metrics_masked = {
        "m_diff":  masked_diff_ratio(ga, gb),
        "m_grid":  masked_grid_ssim(ga, gb, grid=8, worst_frac=1/3),
        "ssim":    ssim_val,
        "hist":    hist_similarity(img_a, img_b_a),
    }
    score_masked = fuse(metrics_masked, WEIGHTS_MASKED)

    # 当前使用的方案
    score = score_masked if weights == WEIGHTS_MASKED else score_full
    metrics = metrics_masked if weights == WEIGHTS_MASKED else metrics_full

    elapsed = int((time.time()-t0)*1000)
    lo, hi = expect
    score_str, ok = cs(score, lo, hi)
    score_full_str, ok_full = cs(score_full, lo, hi)

    if verbose:
        print(f"\n{BOLD}▶ {name}{NC}  {DIM}({note}){NC}")
        print(f"  对齐: {CYAN}{align_method}{NC}  期望: {lo*100:.0f}%~{hi*100:.0f}%")

        # 信息区掩码覆盖率
        mask_a = info_mask(ga)
        info_pct = mask_a.sum() / mask_a.size * 100
        print(f"  信息区覆盖: {info_pct:.1f}%（有内容的像素占比）")

        label_map_full = {
            "diff_ratio": "全图差异面积",
            "grid":       "全图分块最差",
            "ssim":       "全局SSIM",
            "hist":       "颜色直方图",
        }
        label_map_mask = {
            "m_diff": "掩码差异面积",
            "m_grid": "掩码分块最差",
            "ssim":   "全局SSIM",
            "hist":   "颜色直方图",
        }

        print(f"  {DIM}{'─'*54}{NC}")
        print(f"  {'指标':<12}  {'全图方案':>8}  {'掩码方案':>8}  {'权重'}")
        print(f"  {DIM}{'─'*54}{NC}")
        # 对比各指标
        rows = [
            ("差异面积",
             metrics_full.get("diff_ratio", 0),
             metrics_masked.get("m_diff", 0),
             f"{WEIGHTS_FULL.get('diff_ratio',0):.2f} / {WEIGHTS_MASKED.get('m_diff',0):.2f}"),
            ("分块最差",
             metrics_full.get("grid", 0),
             metrics_masked.get("m_grid", 0),
             f"{WEIGHTS_FULL.get('grid',0):.2f} / {WEIGHTS_MASKED.get('m_grid',0):.2f}"),
            ("全局SSIM",
             metrics_full.get("ssim", 0),
             metrics_masked.get("ssim", 0),
             f"{WEIGHTS_FULL.get('ssim',0):.2f} / {WEIGHTS_MASKED.get('ssim',0):.2f}"),
            ("颜色直方图",
             metrics_full.get("hist", 0),
             metrics_masked.get("hist", 0),
             f"{WEIGHTS_FULL.get('hist',0):.2f} / {WEIGHTS_MASKED.get('hist',0):.2f}"),
        ]
        for label, vf, vm, ws in rows:
            # 掩码值比全图值低 → 绿色（改善）；高 → 红色（变差）
            diff_indicator = ""
            if vm < vf - 0.01:
                diff_indicator = f"  {GREEN}↓{NC}"  # 掩码更低（更灵敏）
            elif vm > vf + 0.01:
                diff_indicator = f"  {RED}↑{NC}"    # 掩码更高（意外）
            print(f"  {label:<12}  {vf:8.4f}  {vm:8.4f}  w={ws}{diff_indicator}")

        print(f"  {DIM}{'─'*54}{NC}")
        ok_a = f"{GREEN}✔{NC}" if ok_full else f"{RED}✘{NC}"
        ok_b = f"{GREEN}✔{NC}" if ok else f"{RED}✘{NC}"
        print(f"  {'融合分数':<12}  {score_full_str:>8}  {score_str:>8}  {ok_a} / {ok_b}  ({elapsed}ms)")

    # 保存差异图
    if save_dir:
        os.makedirs(save_dir, exist_ok=True)
        sn = name.replace(" ","_").replace("/","-").replace("(","").replace(")","").replace("×","x")
        diff_uint8 = (diff_map * 255).astype(np.uint8)
        _, thresh = cv2.threshold(diff_uint8, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3,3))
        thresh = cv2.dilate(thresh, kernel)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        annotated = img_a.copy()
        for c in contours:
            if cv2.contourArea(c) < 50: continue
            x, y, w, h = cv2.boundingRect(c)
            cv2.rectangle(annotated, (x,y),(x+w,y+h),(0,0,255),2)
        cv2.imwrite(os.path.join(save_dir, f"{sn}_diff.png"), annotated)

    return score, ok, metrics


# ─── 主函数 ───────────────────────────────────────────────────────────────────

def run_real_dir(real_dir: str, weights: dict, save_dir=None):
    """
    读取真实图片目录，两两配对测试。
    命名规则（任选其一）：
      1. 前缀配对：xxx_A.png / xxx_B.png（同前缀自动配对）
      2. 顺序配对：图片按文件名字母顺序，奇数位为 A、偶数位为 B
    """
    EXTS = {".png", ".jpg", ".jpeg", ".webp"}
    files = sorted([
        f for f in os.listdir(real_dir)
        if os.path.splitext(f.lower())[1] in EXTS
    ])
    if not files:
        print(f"\n{RED}目录 {real_dir} 中没有找到图片文件{NC}")
        print("支持格式：.png .jpg .jpeg .webp")
        return

    hr("═")
    print(f"{BOLD}【真实截图测试】{NC}  目录：{real_dir}")
    print(f"发现 {len(files)} 张图片")
    hr("═")

    # 尝试前缀配对
    map_a, map_b, unmatched = {}, {}, []
    for fname in files:
        prefix = extract_prefix(fname)
        if prefix:
            stem_lower = os.path.splitext(fname)[0].lower()
            if stem_lower.endswith("_a"):
                map_a[prefix] = fname
            else:
                map_b[prefix] = fname
        else:
            unmatched.append(fname)

    pairs = []
    for k in sorted(set(map_a) | set(map_b)):
        if k in map_a and k in map_b:
            pairs.append((map_a[k], map_b[k], k))
        elif k in map_a:
            print(f"  {YELLOW}⚠{NC}  {map_a[k]}  → 无对应 B 图，跳过")
        else:
            print(f"  {YELLOW}⚠{NC}  {map_b[k]}  → 无对应 A 图，跳过")

    # 无法前缀配对的图片按顺序两两配对
    for i in range(0, len(unmatched)-1, 2):
        pairs.append((unmatched[i], unmatched[i+1], f"pair_{i//2+1}"))
    if len(unmatched) % 2 == 1:
        print(f"  {YELLOW}⚠{NC}  {unmatched[-1]}  → 单张无法配对，跳过")

    if not pairs:
        print(f"\n{RED}没有找到有效配对。{NC}")
        print("命名规则：")
        print("  前缀配对：login_A.png + login_B.png")
        print("  顺序配对：文件名按字母顺序，偶数索引为 A，奇数索引为 B")
        return

    print(f"共 {len(pairs)} 对，开始测试...\n")

    results = []
    for a_name, b_name, label in pairs:
        img_a = cv2.imread(os.path.join(real_dir, a_name))
        img_b = cv2.imread(os.path.join(real_dir, b_name))
        if img_a is None or img_b is None:
            print(f"  {RED}✘{NC}  无法读取图片: {a_name} / {b_name}")
            continue

        print(f"{BOLD}▶ [{label}]{NC}")
        print(f"  A: {a_name}  ({img_a.shape[1]}×{img_a.shape[0]})")
        print(f"  B: {b_name}  ({img_b.shape[1]}×{img_b.shape[0]})")

        t0 = time.time()
        img_b_a, align_method, size_warn = align_images(img_a, img_b)
        ga = cv2.cvtColor(img_a,   cv2.COLOR_BGR2GRAY)
        gb = cv2.cvtColor(img_b_a, cv2.COLOR_BGR2GRAY)

        ssim_val, diff_map = ssim_global(ga, gb)

        metrics_full = {
            "diff_ratio": diff_pixel_ratio(ga, gb),
            "grid":       grid_ssim(ga, gb, grid=8, worst_frac=1/3),
            "ssim":       ssim_val,
            "hist":       hist_similarity(img_a, img_b_a),
        }
        score_full = fuse(metrics_full, WEIGHTS_FULL)

        metrics_masked = {
            "m_diff":  masked_diff_ratio(ga, gb),
            "m_grid":  masked_grid_ssim(ga, gb, grid=8, worst_frac=1/3),
            "ssim":    ssim_val,
            "hist":    hist_similarity(img_a, img_b_a),
        }
        score_masked = fuse(metrics_masked, WEIGHTS_MASKED)

        elapsed = int((time.time()-t0)*1000)
        mask_a = info_mask(ga)
        info_pct = mask_a.sum() / mask_a.size * 100

        if size_warn:
            print(f"  对齐: {CYAN}{align_method}{NC}  {YELLOW}⚠ 尺寸差异较大{NC}")
        else:
            print(f"  对齐: {CYAN}{align_method}{NC}  信息区: {info_pct:.1f}%")

        print(f"  {'指标':<12}  {'全图方案':>8}  {'掩码方案':>8}  改善?")
        rows = [
            ("差异面积",  metrics_full["diff_ratio"], metrics_masked["m_diff"]),
            ("分块最差",  metrics_full["grid"],        metrics_masked["m_grid"]),
            ("全局SSIM",  metrics_full["ssim"],        metrics_masked["ssim"]),
            ("颜色直方图", metrics_full["hist"],        metrics_masked["hist"]),
        ]
        for lbl, vf, vm in rows:
            arrow = f"{GREEN}↓{NC}" if vm < vf - 0.005 else (f"{RED}↑{NC}" if vm > vf + 0.005 else "─")
            print(f"  {lbl:<12}  {vf:8.4f}  {vm:8.4f}  {arrow}")

        sf_str, _ = cs(score_full,   0.0, 1.0)   # 只显示颜色，无达标判断
        sm_str, _ = cs(score_masked, 0.0, 1.0)
        # 重新着色
        def score_color(s):
            p = f"{s*100:.1f}%"
            if s >= 0.90: return f"{GREEN}{BOLD}{p}{NC}"
            if s >= 0.60: return f"{YELLOW}{p}{NC}"
            return f"{RED}{p}{NC}"

        diff_score = score_masked - score_full
        arrow_score = f"{GREEN}↓{abs(diff_score)*100:.1f}%{NC}" if diff_score < -0.005 else (
                      f"{RED}↑{abs(diff_score)*100:.1f}%{NC}" if diff_score > 0.005 else "≈")
        print(f"  {'融合分数':<12}  {score_color(score_full):>8}  {score_color(score_masked):>8}  {arrow_score}  ({elapsed}ms)")

        if save_dir:
            os.makedirs(save_dir, exist_ok=True)
            diff_uint8 = (diff_map * 255).astype(np.uint8)
            _, thresh = cv2.threshold(diff_uint8, 0, 255,
                                       cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
            thresh = cv2.dilate(thresh, kernel)
            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL,
                                           cv2.CHAIN_APPROX_SIMPLE)
            annotated = img_a.copy()
            for c in contours:
                if cv2.contourArea(c) < 100: continue
                x, y, w, h = cv2.boundingRect(c)
                cv2.rectangle(annotated, (x, y), (x+w, y+h), (0, 0, 255), 2)
            sn = label.replace(" ", "_")
            cv2.imwrite(os.path.join(save_dir, f"real_{sn}_A.png"),  img_a)
            cv2.imwrite(os.path.join(save_dir, f"real_{sn}_B.png"),  img_b_a)
            cv2.imwrite(os.path.join(save_dir, f"real_{sn}_diff.png"), annotated)
            print(f"  差异图已保存 → real_{sn}_diff.png")

        results.append((label, score_full, score_masked, metrics_full, metrics_masked))
        print()

    # 汇总
    if len(results) > 1:
        hr("═")
        print(f"\n{BOLD}真实图片测试汇总{NC}\n")
        print(f"  {'配对':<28} {'全图方案':>9} {'掩码方案':>9}  改善?")
        hr()
        for label, sf, sm, mf, mm in results:
            def sc(s):
                p = f"{s*100:.1f}%"
                if s >= 0.90: return f"{GREEN}{BOLD}{p}{NC}"
                if s >= 0.60: return f"{YELLOW}{p}{NC}"
                return f"{RED}{p}{NC}"
            d = sm - sf
            arr = f"{GREEN}↓{abs(d)*100:.1f}%{NC}" if d < -0.005 else (
                  f"{RED}↑{abs(d)*100:.1f}%{NC}" if d > 0.005 else "≈")
            print(f"  {label:<28} {sc(sf):>9}  {sc(sm):>9}  {arr}")
        hr("═")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--save-images", action="store_true",
                        help="保存 A/B/差异图到 tests/algo_output/")
    parser.add_argument("--real-dir", type=str, default=None,
                        help="真实截图目录路径（不传则运行合成图测试）")
    parser.add_argument("--doc", action="store_true",
                        help="文档对比模式：LANCZOS4对齐 + 低阈值，同时对比标准模式 vs 文档模式")
    args = parser.parse_args()

    save_dir = os.path.join(BACKEND_DIR, "tests", "algo_output") if args.save_images else None

    if args.real_dir and args.doc:
        # ── 文档对比模式 ────────────────────────────────────────────────────
        run_doc_real_dir(args.real_dir, save_dir)
    elif args.real_dir:
        # ── 真实截图模式 ────────────────────────────────────────────────────
        run_real_dir(args.real_dir, WEIGHTS, save_dir)
    else:
        # ── 合成图测试模式 ──────────────────────────────────────────────────
        cases = build_cases()
        weights = WEIGHTS

        hr("═")
        print(f"{BOLD}Graph Compare — 对比算法测试（聚焦相同场景内容变化）{NC}")
        print(f"公式：diff_ratio^{weights['diff_ratio']} × grid_8×8^{weights['grid']} "
              f"× ssim^{weights['ssim']} × hist^{weights['hist']}")
        hr("═")

        results = []
        for row in cases:
            name, img_a, img_b, expect, note = row
            score, ok, metrics = run_case(name, img_a, img_b, expect, note,
                                          weights, save_dir)
            results.append((name, score, ok, expect, metrics))

        hr("═")
        print(f"\n{BOLD}汇总结果{NC}\n")
        header = (f"  {'Case':<28} {'diff_ratio':>10} {'grid':>6} "
                  f"{'ssim':>6} {'hist':>6}   {'期望区间':>12}   {'分数':>8}  达标")
        print(header)
        hr()
        passed = 0
        for name, score, ok, expect, m in results:
            lo, hi = expect
            sc_str, _ = cs(score, lo, hi)
            ok_mark = f"{GREEN}✔{NC}" if ok else f"{RED}✘{NC}"
            if ok: passed += 1
            print(f"  {name:<28} {m['diff_ratio']:10.4f} {m['grid']:6.4f} "
                  f"{m['ssim']:6.4f} {m['hist']:6.4f}  "
                  f"  {lo*100:.0f}%~{hi*100:.0f}%   {sc_str:>8}  {ok_mark}")

        hr("═")
        rate = passed / len(results)
        rate_str = (f"{GREEN}{BOLD}" if rate >= 0.8 else
                    f"{YELLOW}{BOLD}" if rate >= 0.6 else f"{RED}{BOLD}")
        print(f"\n  达标率：{rate_str}{passed}/{len(results)}  ({rate*100:.0f}%){NC}")

        # 前缀提取验证
        hr("═")
        print(f"\n{BOLD}【前缀提取测试】{NC}")
        prefix_cases = [
            ("homepage_A.png",   "homepage"),
            ("login_v2_B.jpg",   "login_v2"),
            ("test_a.PNG",       "test"),
            ("screen_B.webp",    "screen"),
            ("nomark.png",        None),
            ("a_b_c.png",         None),
            ("abc_A_extra.png",   None),
        ]
        pfx_ok = 0
        for fname, expected in prefix_cases:
            got = extract_prefix(fname)
            ok = got == expected
            if ok: pfx_ok += 1
            mark = f"{GREEN}✔{NC}" if ok else f"{RED}✘{NC}"
            print(f"  {mark}  {fname:<32} 期望={str(expected):<14} 得到={str(got)}")
        print(f"\n  前缀提取：{pfx_ok}/{len(prefix_cases)} 通过 "
              f"{'✔' if pfx_ok==len(prefix_cases) else '✘'}")
        hr("═")

    if save_dir:
        print(f"\n  图片已保存到: {save_dir}/")


if __name__ == "__main__":
    main()
