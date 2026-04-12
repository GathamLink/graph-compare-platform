"""
Task 业务逻辑服务
"""
import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models import Task, Image, DiffResult
from schemas import TaskCreate, TaskUpdate
from services.oss_service import delete_from_oss


# ─────────────────────────────────────────────
# 辅助
# ─────────────────────────────────────────────

def get_task_or_404(db: Session, task_id: int) -> Task:
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return task


def _calc_pair_count(task: Task) -> int:
    a = sum(1 for img in task.images if img.group == "A")
    b = sum(1 for img in task.images if img.group == "B")
    return max(a, b)


# ─────────────────────────────────────────────
# CRUD
# ─────────────────────────────────────────────

def list_tasks(
    db: Session,
    page: int = 1,
    page_size: int = 20,
    search: Optional[str] = None,
    status: Optional[str] = None,
):
    query = db.query(Task)
    if search:
        query = query.filter(Task.name.ilike(f"%{search}%"))
    if status:
        query = query.filter(Task.status == status)

    total = query.count()
    tasks = (
        query.order_by(Task.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return total, tasks


def create_task(db: Session, data: TaskCreate) -> Task:
    task = Task(
        name=data.name,
        description=data.description,
        pair_mode=data.pair_mode,
        diff_algo=data.diff_algo,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def get_task(db: Session, task_id: int) -> Task:
    return get_task_or_404(db, task_id)


def update_task(db: Session, task_id: int, data: TaskUpdate) -> Task:
    task = get_task_or_404(db, task_id)
    if data.name is not None:
        task.name = data.name
    if data.description is not None:
        task.description = data.description
    if data.status is not None:
        task.status = data.status
    if data.pair_mode is not None:
        task.pair_mode = data.pair_mode
    if data.diff_algo is not None:
        task.diff_algo = data.diff_algo
    task.updated_at = datetime.datetime.utcnow()
    db.commit()
    db.refresh(task)
    return task


def delete_task(db: Session, task_id: int) -> None:
    task = get_task_or_404(db, task_id)

    # 级联删除所有 OSS 对象（图片 + 差异图）
    for img in task.images:
        delete_from_oss(img.oss_key)
    for diff in task.diff_results:
        delete_from_oss(diff.diff_oss_key)

    db.delete(task)
    db.commit()


def get_task_pair_count(task: Task) -> int:
    return _calc_pair_count(task)
