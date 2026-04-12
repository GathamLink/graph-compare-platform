from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db
from schemas import (
    TaskCreate, TaskUpdate, TaskListResponse, TaskListItem, TaskDetail, ImageBrief
)
from services import task_service
from services.image_service import image_to_brief

router = APIRouter(prefix="/tasks", tags=["tasks"])

# 允许的 status 值
VALID_STATUSES = {"draft", "active", "completed"}


def _to_task_list_item(task, db) -> TaskListItem:
    return TaskListItem(
        id=task.id,
        name=task.name,
        description=task.description,
        status=task.status,
        pair_mode=task.pair_mode,
        diff_algo=getattr(task, "diff_algo", "balanced") or "balanced",
        pair_count=task_service.get_task_pair_count(task),
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def _to_task_detail(task) -> TaskDetail:
    group_a = sorted([img for img in task.images if img.group == "A"], key=lambda x: x.sort_order)
    group_b = sorted([img for img in task.images if img.group == "B"], key=lambda x: x.sort_order)
    return TaskDetail(
        id=task.id,
        name=task.name,
        description=task.description,
        status=task.status,
        pair_mode=task.pair_mode,
        diff_algo=getattr(task, "diff_algo", "balanced") or "balanced",
        pair_count=max(len(group_a), len(group_b)),
        created_at=task.created_at,
        updated_at=task.updated_at,
        group_a=[ImageBrief(**image_to_brief(img)) for img in group_a],
        group_b=[ImageBrief(**image_to_brief(img)) for img in group_b],
    )


@router.get("", response_model=TaskListResponse)
async def list_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
    status: Optional[str] = Query(None),   # 不在这里做 pattern，手动校验避免 422
    db: Session = Depends(get_db),
):
    # 空字符串视为不筛选
    status_filter = status.strip() if status else None
    if status_filter == "":
        status_filter = None
    # 非法值才返回 400
    if status_filter and status_filter not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"status 参数非法，允许值：{sorted(VALID_STATUSES)}"
        )
    total, tasks = task_service.list_tasks(db, page, page_size, search, status_filter)
    return TaskListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[_to_task_list_item(t, db) for t in tasks],
    )


@router.post("", response_model=TaskDetail, status_code=201)
async def create_task(data: TaskCreate, db: Session = Depends(get_db)):
    task = task_service.create_task(db, data)
    return _to_task_detail(task)


@router.get("/{task_id}", response_model=TaskDetail)
async def get_task(task_id: int, db: Session = Depends(get_db)):
    task = task_service.get_task(db, task_id)
    return _to_task_detail(task)


@router.put("/{task_id}", response_model=TaskDetail)
async def update_task(task_id: int, data: TaskUpdate, db: Session = Depends(get_db)):
    task = task_service.update_task(db, task_id, data)
    return _to_task_detail(task)


@router.delete("/{task_id}", status_code=204)
async def delete_task(task_id: int, db: Session = Depends(get_db)):
    task_service.delete_task(db, task_id)
