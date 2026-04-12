from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List
from datetime import datetime

VALID_PAIR_MODES  = {"sequential", "prefix"}
VALID_DIFF_ALGOS  = {"balanced", "document", "structural", "pixel_exact"}


# ─────────────────────────────────────────────
# Task Schemas
# ─────────────────────────────────────────────

class TaskCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    pair_mode: str = Field("sequential", pattern="^(sequential|prefix)$")
    diff_algo: str = Field("balanced", pattern="^(balanced|document|structural|pixel_exact)$")


class TaskUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    status: Optional[str] = Field(None, pattern="^(draft|active|completed)$")
    pair_mode: Optional[str] = Field(None, pattern="^(sequential|prefix)$")
    diff_algo: Optional[str] = Field(None, pattern="^(balanced|document|structural|pixel_exact)$")


class ImageBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    image_id: int = 0          # 兼容字段，等于 id
    sort_order: int
    original_name: str
    url: str
    thumb_url: Optional[str] = None   # 200px 缩略图 URL，无时降级为原图 URL
    width: Optional[int]
    height: Optional[int]
    created_at: datetime


class TaskListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str]
    status: str
    pair_mode: str = "sequential"
    diff_algo: str = "balanced"
    pair_count: int
    created_at: datetime
    updated_at: datetime


class TaskDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str]
    status: str
    pair_mode: str = "sequential"
    diff_algo: str = "balanced"
    pair_count: int
    created_at: datetime
    updated_at: datetime
    group_a: List[ImageBrief] = []
    group_b: List[ImageBrief] = []


class TaskListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[TaskListItem]


# ─────────────────────────────────────────────
# Image Schemas
# ─────────────────────────────────────────────

class ImageUploadResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    image_id: int
    original_name: str
    sort_order: int
    url: str
    width: Optional[int]
    height: Optional[int]


class BatchAppendResult(BaseModel):
    task_id: int
    appended: dict  # {"group_a": [...], "group_b": [...]}
    diff_triggered: bool


class ReorderRequest(BaseModel):
    group: str = Field(..., pattern="^[AB]$")
    order: List[int] = Field(..., min_length=1)  # 按新顺序排列的 image id 列表


# ─────────────────────────────────────────────
# Diff Schemas
# ─────────────────────────────────────────────

class DiffStatusResponse(BaseModel):
    task_id: int
    total: int
    done: int
    running: int
    pending: int
    failed: int


class ImageInfo(BaseModel):
    id: int
    url: str
    original_name: str
    width: Optional[int]
    height: Optional[int]


class DiffPairResult(BaseModel):
    pair_index: int
    pair_key: Optional[str] = None   # prefix 模式下的配对前缀（如 "xxxx"）
    status: str
    image_a: Optional[ImageInfo]
    image_b: Optional[ImageInfo]
    diff_url: Optional[str]
    diff_score: Optional[float]
    is_similar: Optional[bool] = None   # score >= 0.75 为 True，低于则为 False（差异显著）
    align_method: Optional[str]
    size_warning: bool = False


# ─────────────────────────────────────────────
# Generic Error Response
# ─────────────────────────────────────────────

class ErrorResponse(BaseModel):
    code: int
    message: str
    detail: Optional[str] = None
