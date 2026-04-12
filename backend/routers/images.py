from typing import List, Optional
import io, zipfile, os

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from schemas import ImageUploadResult, BatchAppendResult, ReorderRequest
from services import image_service
from services.image_service import image_to_brief
from services.diff_service import run_diff_for_new_pairs

router = APIRouter(prefix="/tasks/{task_id}/images", tags=["images"])

# 允许的图片扩展名
ALLOWED_IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}

# ZIP 内预期的目录名（大小写不敏感）
EXPECTED_DIRS = {'原图', '对比图'}


@router.post("", response_model=List[ImageUploadResult], status_code=201)
async def upload_images(
    task_id: int,
    group: str = Form(..., pattern="^[AB]$"),
    files: List[UploadFile] = File(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: Session = Depends(get_db),
):
    """单组图片上传（group=A 或 B，支持多文件）"""
    images = await image_service.upload_images(db, task_id, group, files)
    background_tasks.add_task(run_diff_for_new_pairs, task_id)
    return [ImageUploadResult(**image_to_brief(img)) for img in images]


@router.post("/batch-append", response_model=BatchAppendResult, status_code=201)
async def batch_append_images(
    task_id: int,
    images_a: Optional[List[UploadFile]] = File(default=[]),
    images_b: Optional[List[UploadFile]] = File(default=[]),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: Session = Depends(get_db),
):
    """批量追加图片：同时向 A/B 两组追加，两组可不等长。"""
    if not images_a and not images_b:
        raise HTTPException(status_code=400, detail="images_a 和 images_b 至少需要传一个")

    results_a, results_b = await image_service.batch_append_images(
        db, task_id, images_a or [], images_b or []
    )

    if results_a or results_b:
        background_tasks.add_task(run_diff_for_new_pairs, task_id)

    return BatchAppendResult(
        task_id=task_id,
        appended={
            "group_a": [image_to_brief(img) for img in results_a],
            "group_b": [image_to_brief(img) for img in results_b],
        },
        diff_triggered=bool(results_a or results_b),
    )


@router.post("/import-zip", response_model=BatchAppendResult, status_code=201)
async def import_zip(
    task_id: int,
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: Session = Depends(get_db),
):
    """
    ZIP 压缩包批量导入。

    ZIP 内必须包含两个目录：
        原图/       （对应 A 组）
        对比图/     （对应 B 组）

    每个目录内只放图片文件（.jpg/.jpeg/.png/.webp/.gif）。
    两组按文件名字母顺序排序后依次配对，可以不等长。
    不允许包含子目录（目录内不能再嵌套目录）。
    """
    # ── 校验文件类型 ─────────────────────────────────────────────────────────
    filename = file.filename or ''
    if not filename.lower().endswith('.zip'):
        raise HTTPException(status_code=400, detail="只接受 .zip 格式的压缩包")

    raw = await file.read()
    if len(raw) == 0:
        raise HTTPException(status_code=400, detail="上传的文件为空")

    # ── 解压 ─────────────────────────────────────────────────────────────────
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="文件不是有效的 ZIP 压缩包")

    # ── 分析目录结构 ──────────────────────────────────────────────────────────

    def _decode_zip_name(info: zipfile.ZipInfo) -> str:
        """
        正确解码 ZIP 条目文件名。
        - 若 flag_bits bit 11 置位 → 文件名已是 UTF-8，直接用
        - 否则先尝试 UTF-8，失败则尝试 GBK（Windows/macOS 中文路径常见编码）
        """
        raw_bytes = info.filename.encode('cp437')   # zipfile 默认用 cp437 解码，反转回原始字节
        if info.flag_bits & 0x800:                  # UTF-8 flag
            return raw_bytes.decode('utf-8', errors='replace')
        for enc in ('utf-8', 'gbk', 'gb2312', 'big5'):
            try:
                return raw_bytes.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return raw_bytes.decode('utf-8', errors='replace')

    # 构建 {正确文件名: ZipInfo} 映射
    name_map: dict[str, zipfile.ZipInfo] = {}
    for info in zf.infolist():
        correct_name = _decode_zip_name(info)
        name_map[correct_name] = info

    # 过滤 macOS 自动生成的垃圾文件，只保留真实文件（不含目录条目）
    all_names = [
        n for n in name_map
        if not n.startswith('__MACOSX')
        and '/.DS_Store' not in n
        and n != '.DS_Store'
        and not n.endswith('/')
    ]

    EXPECTED = {'原图', '对比图'}

    # 从所有文件路径中推断 prefix（不依赖目录条目是否存在）
    # 支持两种结构：
    #   直接：  原图/xxx.png          → prefix = ''
    #   包裹：  root/原图/xxx.png     → prefix = 'root/'
    prefix = None

    for name in all_names:
        parts = name.strip('/').split('/')
        if len(parts) >= 2 and parts[-2] in EXPECTED:
            # 文件直接在 原图/ 或 对比图/ 下
            # parts = ['原图', 'xxx.png'] → prefix = ''
            # parts = ['root', '原图', 'xxx.png'] → prefix = 'root/'
            if parts[0] in EXPECTED:
                prefix = ''
            else:
                prefix = parts[0] + '/'
            break

    if prefix is None:
        # 尝试两层包裹：root/sub/原图/xxx.png
        for name in all_names:
            parts = name.strip('/').split('/')
            if len(parts) >= 3 and parts[-2] in EXPECTED:
                prefix = '/'.join(parts[:-2]) + '/'
                break

    if prefix is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "ZIP 中未找到 '原图' 和 '对比图' 目录，请检查压缩包结构。\n"
                "预期结构：\n"
                "  root/（名称随意）\n"
                "    原图/xxx.png\n"
                "    对比图/xxx.png"
            )
        )

    def _collect_images(dir_name: str) -> list[tuple[str, bytes]]:
        """收集 ZIP 内指定目录的图片，返回 [(文件名, 内容), ...] 按文件名排序"""
        result = []
        full_dir = prefix + dir_name + '/'
        for name in sorted(all_names):
            if not name.startswith(full_dir):
                continue
            rel = name[len(full_dir):]
            if not rel or rel.endswith('/'):
                continue  # 跳过目录项本身
            if '/' in rel:
                raise HTTPException(
                    status_code=400,
                    detail=f"目录 '{dir_name}' 中包含子目录，不支持嵌套结构。请将图片直接放在目录下。"
                )
            ext = os.path.splitext(rel)[1].lower()
            if ext not in ALLOWED_IMAGE_EXTS:
                continue  # 跳过非图片文件
            # 用 name_map 中的原始 ZipInfo 读取（绕过乱码文件名问题）
            data = zf.read(name_map[name])
            result.append((rel, data))
        return result

    # ── 读取两组文件 ───────────────────────────────────────────────────────────
    try:
        files_a = _collect_images('原图')
        files_b = _collect_images('对比图')
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"解压时出错：{e}")

    if not files_a and not files_b:
        raise HTTPException(
            status_code=400,
            detail="ZIP 中未找到 '原图' 和 '对比图' 目录，请检查压缩包结构。\n"
                   "预期结构：\n  原图/xxx.png\n  对比图/xxx.png"
        )
    if not files_a:
        raise HTTPException(status_code=400, detail="ZIP 中未找到 '原图' 目录或其中没有图片文件")
    if not files_b:
        raise HTTPException(status_code=400, detail="ZIP 中未找到 '对比图' 目录或其中没有图片文件")

    # ── 构造 UploadFile 列表并批量写入 ─────────────────────────────────────────
    import mimetypes
    from fastapi.datastructures import UploadFile as FastAPIUploadFile

    def _make_upload_file(fname: str, data: bytes) -> UploadFile:
        mime = mimetypes.guess_type(fname)[0] or 'image/png'
        return UploadFile(filename=fname, file=io.BytesIO(data), size=len(data),
                          headers={'content-type': mime})  # type: ignore

    upload_a = [_make_upload_file(n, d) for n, d in files_a]
    upload_b = [_make_upload_file(n, d) for n, d in files_b]

    results_a, results_b = await image_service.batch_append_images(db, task_id, upload_a, upload_b)

    if results_a or results_b:
        background_tasks.add_task(run_diff_for_new_pairs, task_id)

    return BatchAppendResult(
        task_id=task_id,
        appended={
            "group_a": [image_to_brief(img) for img in results_a],
            "group_b": [image_to_brief(img) for img in results_b],
        },
        diff_triggered=bool(results_a or results_b),
    )


@router.delete("/{image_id}", status_code=204)
async def delete_image(task_id: int, image_id: int, db: Session = Depends(get_db)):
    """删除单张图片（同步删除 OSS 对象及关联 diff_results）"""
    image_service.delete_image(db, task_id, image_id)


@router.patch("/reorder")
async def reorder_images(
    task_id: int,
    data: ReorderRequest,
    db: Session = Depends(get_db),
):
    """重新排序图片（影响配对关系）"""
    images = image_service.reorder_images(db, task_id, data.group, data.order)
    return {
        "task_id": task_id,
        "group": data.group,
        "reordered": [image_to_brief(img) for img in images],
    }
