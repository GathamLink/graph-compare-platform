from sqlalchemy import (
    Column, Integer, String, Float, Boolean,
    DateTime, ForeignKey, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from database import Base
import datetime


class Task(Base):
    __tablename__ = "tasks"

    id          = Column(Integer, primary_key=True, index=True)
    name        = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status      = Column(String(20), default="draft")       # draft | active | completed
    pair_mode   = Column(String(20), default="sequential")  # sequential | prefix
    diff_algo   = Column(String(20), default="balanced")    # balanced | pixel | structural
    created_at  = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at  = Column(
        DateTime,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
    )

    images       = relationship("Image", back_populates="task", cascade="all, delete-orphan")
    diff_results = relationship("DiffResult", back_populates="task", cascade="all, delete-orphan")


class Image(Base):
    __tablename__ = "images"

    id            = Column(Integer, primary_key=True, index=True)
    task_id       = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    group         = Column(String(1), nullable=False)      # 'A' or 'B'
    sort_order    = Column(Integer, nullable=False)         # 0-based，决定配对关系
    oss_key       = Column(String(512), nullable=False)    # MinIO 对象 Key
    thumb_oss_key = Column(String(512), nullable=True)     # 200px 宽缩略图 Key（可选）
    original_name = Column(String(255), nullable=False)    # 原始文件名（仅展示用）
    file_size     = Column(Integer, nullable=False)        # 字节
    mime_type     = Column(String(50), nullable=False)
    width         = Column(Integer, nullable=True)         # px
    height        = Column(Integer, nullable=True)         # px
    created_at    = Column(DateTime, default=datetime.datetime.utcnow)

    task = relationship("Task", back_populates="images")


class DiffResult(Base):
    __tablename__ = "diff_results"
    __table_args__ = (
        # (image_a_id, image_b_id) 联合唯一索引，用于增量跳过已计算配对
        UniqueConstraint("image_a_id", "image_b_id", name="uq_diff_pair"),
    )

    id           = Column(Integer, primary_key=True, index=True)
    task_id      = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    image_a_id   = Column(Integer, ForeignKey("images.id"), nullable=False)
    image_b_id   = Column(Integer, ForeignKey("images.id"), nullable=False)
    pair_index   = Column(Integer, nullable=False)          # 0-based
    diff_oss_key = Column(String(512), nullable=True)       # 差异图 MinIO Key
    diff_score   = Column(Float, nullable=True)             # SSIM 分数（0~1）
    align_method = Column(String(20), default="resize")     # resize | feature | none
    size_warning = Column(Boolean, default=False)           # 尺寸差异 >10% 时为 True
    status       = Column(String(20), default="pending")    # pending|running|done|failed
    created_at   = Column(DateTime, default=datetime.datetime.utcnow)

    task = relationship("Task", back_populates="diff_results")
