from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Image, DiffResult
from schemas import DiffStatusResponse, DiffPairResult, ImageInfo
from services import diff_service
from services.diff_service import SIMILARITY_THRESHOLD
from services.oss_service import get_public_url

router = APIRouter(prefix="/tasks/{task_id}", tags=["diff"])


@router.get("/diff-status", response_model=DiffStatusResponse)
async def get_diff_status(task_id: int, db: Session = Depends(get_db)):
    """查询任务差异计算进度（轻量查询，不阻塞线程）"""
    return diff_service.get_diff_status(db, task_id)


@router.get("/diff/{pair_index}", response_model=DiffPairResult)
async def get_diff_pair(task_id: int, pair_index: int, db: Session = Depends(get_db)):
    """获取指定对（pair_index 0-based）的差异结果"""
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

    img_a = images_a[pair_index] if pair_index < len(images_a) else None
    img_b = images_b[pair_index] if pair_index < len(images_b) else None

    if img_a is None and img_b is None:
        raise HTTPException(status_code=404, detail=f"pair_index {pair_index} 不存在")

    diff_record = diff_service.get_diff_pair(db, task_id, pair_index)

    score = diff_record.diff_score if diff_record else None
    is_similar = (score >= SIMILARITY_THRESHOLD) if score is not None else None

    return DiffPairResult(
        pair_index=pair_index,
        status=diff_record.status if diff_record else "pending",
        image_a=ImageInfo(
            id=img_a.id,
            url=get_public_url(img_a.oss_key),
            original_name=img_a.original_name,
            width=img_a.width,
            height=img_a.height,
        ) if img_a else None,
        image_b=ImageInfo(
            id=img_b.id,
            url=get_public_url(img_b.oss_key),
            original_name=img_b.original_name,
            width=img_b.width,
            height=img_b.height,
        ) if img_b else None,
        diff_url=get_public_url(diff_record.diff_oss_key) if diff_record and diff_record.diff_oss_key else None,
        diff_score=score,
        is_similar=is_similar,
        align_method=diff_record.align_method if diff_record else None,
        size_warning=diff_record.size_warning if diff_record else False,
    )


@router.post("/diff/compute", status_code=202)
async def trigger_diff_compute(
    task_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """手动触发整个任务的差异计算（全量重算）"""
    # 重置所有非 done 状态的记录，强制重算
    db.query(DiffResult).filter(
        DiffResult.task_id == task_id,
    ).update({"status": "pending"})
    db.commit()

    background_tasks.add_task(diff_service.run_diff_for_new_pairs, task_id)
    return {"message": "差异计算已触发", "task_id": task_id, "threshold": SIMILARITY_THRESHOLD}
