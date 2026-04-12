"""
Image 业务逻辑服务
- 单组上传
- 批量追加
- 删除
- 重排序
"""
import io
from typing import List

from fastapi import HTTPException, UploadFile
from PIL import Image as PILImage
from sqlalchemy.orm import Session

from models import Image, Task
from services.oss_service import upload_to_oss, delete_from_oss, get_public_url
from services.task_service import get_task_or_404

# 允许的 MIME 类型
ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB


# ─────────────────────────────────────────────
# 辅助
# ─────────────────────────────────────────────

def _get_max_sort_order(db: Session, task_id: int, group: str) -> int:
    """返回该组当前最大 sort_order，无图片时返回 -1"""
    from sqlalchemy import func
    result = (
        db.query(func.max(Image.sort_order))
        .filter(Image.task_id == task_id, Image.group == group)
        .scalar()
    )
    return result if result is not None else -1


def _read_image_size(data: bytes) -> tuple[int | None, int | None]:
    """用 Pillow 读取图片尺寸，失败时返回 (None, None)"""
    try:
        with PILImage.open(io.BytesIO(data)) as img:
            return img.width, img.height
    except Exception:
        return None, None


THUMB_WIDTH = 200   # 缩略图宽度（px），高度等比缩放


def _generate_thumbnail(data: bytes, mime_type: str) -> bytes | None:
    """
    用 Pillow 生成宽度 200px 的缩略图（WEBP 格式，质量 75）。
    失败时返回 None（静默降级，不影响主流程）。
    """
    try:
        with PILImage.open(io.BytesIO(data)) as img:
            # EXIF 自动旋转
            try:
                from PIL import ImageOps
                img = ImageOps.exif_transpose(img)
            except Exception:
                pass
            # 等比缩放
            w, h = img.size
            if w <= THUMB_WIDTH:
                # 原图本来就小，直接用原图数据
                return data
            new_h = int(h * THUMB_WIDTH / w)
            img = img.resize((THUMB_WIDTH, new_h), PILImage.LANCZOS)
            # 转 RGB（去除 alpha，避免 JPEG 模式报错）
            if img.mode in ("RGBA", "P", "LA"):
                bg = PILImage.new("RGB", img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
                img = bg
            elif img.mode != "RGB":
                img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="WEBP", quality=75, method=4)
            return buf.getvalue()
    except Exception:
        return None


def _validate_file(file: UploadFile) -> None:
    if file.content_type not in ALLOWED_MIME:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型 '{file.content_type}'，仅允许 jpg/png/webp/gif",
        )


async def _create_image_record(
    db: Session,
    task_id: int,
    group: str,
    file: UploadFile,
    sort_order: int,
) -> Image:
    """上传文件到 OSS（含缩略图）并写入数据库，返回 Image 对象"""
    _validate_file(file)
    data = await file.read()

    if len(data) > MAX_SIZE_BYTES:
        raise HTTPException(status_code=400, detail=f"文件 '{file.filename}' 超过 20MB 限制")

    import os, uuid
    from services import oss_service
    oss_service.ensure_bucket()

    ext = os.path.splitext(file.filename or "")[1].lower() or ".bin"
    oss_key = f"images/{uuid.uuid4().hex}{ext}"
    oss_service.client.put_object(
        oss_service.BUCKET,
        oss_key,
        data=io.BytesIO(data),
        length=len(data),
        content_type=file.content_type or "application/octet-stream",
    )

    # 生成并上传缩略图（失败不影响主流程）
    thumb_oss_key = None
    thumb_data = _generate_thumbnail(data, file.content_type or "")
    if thumb_data:
        thumb_oss_key = f"thumbs/{uuid.uuid4().hex}.webp"
        try:
            oss_service.client.put_object(
                oss_service.BUCKET,
                thumb_oss_key,
                data=io.BytesIO(thumb_data),
                length=len(thumb_data),
                content_type="image/webp",
            )
        except Exception:
            thumb_oss_key = None

    width, height = _read_image_size(data)

    img = Image(
        task_id=task_id,
        group=group,
        sort_order=sort_order,
        oss_key=oss_key,
        thumb_oss_key=thumb_oss_key,
        original_name=file.filename or "unknown",
        file_size=len(data),
        mime_type=file.content_type or "application/octet-stream",
        width=width,
        height=height,
    )
    db.add(img)
    db.flush()
    return img


def image_to_brief(img: Image) -> dict:
    thumb_key = getattr(img, "thumb_oss_key", None)
    return {
        "id": img.id,
        "image_id": img.id,
        "sort_order": img.sort_order,
        "original_name": img.original_name,
        "url": get_public_url(img.oss_key),
        "thumb_url": get_public_url(thumb_key) if thumb_key else get_public_url(img.oss_key),
        "width": img.width,
        "height": img.height,
        "created_at": img.created_at,
    }


# ─────────────────────────────────────────────
# 单组上传
# ─────────────────────────────────────────────

async def upload_images(
    db: Session,
    task_id: int,
    group: str,
    files: List[UploadFile],
) -> List[Image]:
    get_task_or_404(db, task_id)
    max_order = _get_max_sort_order(db, task_id, group)
    results = []
    for i, file in enumerate(files):
        img = await _create_image_record(db, task_id, group, file, max_order + i + 1)
        results.append(img)
    db.commit()
    for img in results:
        db.refresh(img)
    return results


# ─────────────────────────────────────────────
# 批量追加（A/B 同时）
# ─────────────────────────────────────────────

async def batch_append_images(
    db: Session,
    task_id: int,
    files_a: List[UploadFile],
    files_b: List[UploadFile],
) -> tuple[List[Image], List[Image]]:
    get_task_or_404(db, task_id)
    max_a = _get_max_sort_order(db, task_id, "A")
    max_b = _get_max_sort_order(db, task_id, "B")

    results_a: List[Image] = []
    for i, file in enumerate(files_a):
        img = await _create_image_record(db, task_id, "A", file, max_a + i + 1)
        results_a.append(img)

    results_b: List[Image] = []
    for i, file in enumerate(files_b):
        img = await _create_image_record(db, task_id, "B", file, max_b + i + 1)
        results_b.append(img)

    db.commit()
    for img in results_a + results_b:
        db.refresh(img)
    return results_a, results_b


# ─────────────────────────────────────────────
# 删除单张图片
# ─────────────────────────────────────────────

def delete_image(db: Session, task_id: int, image_id: int) -> None:
    img = (
        db.query(Image)
        .filter(Image.id == image_id, Image.task_id == task_id)
        .first()
    )
    if not img:
        raise HTTPException(status_code=404, detail=f"Image {image_id} not found in task {task_id}")

    # 删除关联的 diff_results
    from models import DiffResult
    diffs = (
        db.query(DiffResult)
        .filter(
            (DiffResult.image_a_id == image_id) | (DiffResult.image_b_id == image_id)
        )
        .all()
    )
    for diff in diffs:
        delete_from_oss(diff.diff_oss_key)
        db.delete(diff)

    delete_from_oss(img.oss_key)
    db.delete(img)
    db.commit()


# ─────────────────────────────────────────────
# 重新排序
# ─────────────────────────────────────────────

def reorder_images(db: Session, task_id: int, group: str, ordered_ids: List[int]) -> List[Image]:
    """按给定 id 顺序重新写入 sort_order"""
    get_task_or_404(db, task_id)
    images = (
        db.query(Image)
        .filter(Image.task_id == task_id, Image.group == group)
        .all()
    )
    id_to_img = {img.id: img for img in images}

    # 校验 id 是否都属于本任务本组
    for i, img_id in enumerate(ordered_ids):
        if img_id not in id_to_img:
            raise HTTPException(
                status_code=400,
                detail=f"Image {img_id} 不属于任务 {task_id} 的 {group} 组",
            )
        id_to_img[img_id].sort_order = i

    db.commit()
    return [id_to_img[img_id] for img_id in ordered_ids]
