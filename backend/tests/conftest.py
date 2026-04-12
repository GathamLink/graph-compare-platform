"""
conftest.py — pytest 全局夹具

核心策略：
- 用单一 SQLite 内存 connection + StaticPool，保证所有 session 共享同一物理连接
- 每个测试用 SAVEPOINT（nested transaction）隔离，测试结束回滚
- 全局 patch services.oss_service.client → MockMinioClient
"""
import io
import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

# ── sys.path ─────────────────────────────────────────────────────────────────
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# ── 环境变量（import 业务模块之前）────────────────────────────────────────────
os.environ["DATABASE_URL"]     = "sqlite://"
os.environ["MINIO_ENDPOINT"]   = "localhost:19012"
os.environ["MINIO_ACCESS_KEY"] = "minioadmin"
os.environ["MINIO_SECRET_KEY"] = "minioadmin"
os.environ["MINIO_BUCKET"]     = "test-bucket"
os.environ["CORS_ORIGINS"]     = "http://localhost:13010"

# ─────────────────────────────────────────────
# Mock MinIO
# ─────────────────────────────────────────────

class MockMinioClient:
    def __init__(self):
        self._store: dict[str, bytes] = {}

    def bucket_exists(self, bucket):       return True
    def make_bucket(self, bucket):         pass
    def set_bucket_policy(self, *a):       pass
    def list_buckets(self):                return []

    def put_object(self, bucket, key, data, length, content_type=None, **kw):
        self._store[key] = data.read() if hasattr(data, "read") else bytes(data)

    def get_object(self, bucket, key):
        m = MagicMock()
        m.read.return_value = self._store.get(key, b"")
        m.close = MagicMock()
        return m

    def remove_object(self, bucket, key):
        self._store.pop(key, None)


_mock_minio = MockMinioClient()

# patch OSS 客户端（在 import 业务模块之前）
_oss_patch = patch("services.oss_service.client", _mock_minio)
_oss_patch.start()

# ─────────────────────────────────────────────
# 共享内存数据库（StaticPool = 单连接）
# ─────────────────────────────────────────────
import database as _db_module   # noqa: E402

_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSession = sessionmaker(bind=_engine, autocommit=False, autoflush=False)

# 替换 database 模块里的 engine/SessionLocal
_db_module.engine       = _engine
_db_module.SessionLocal = _TestSession

from database import Base, get_db  # noqa: E402

# 建表（只做一次）
Base.metadata.create_all(bind=_engine)

# 现在才安全 import main
from main import app  # noqa: E402

# ─────────────────────────────────────────────
# 每个测试：清空所有表数据（保留表结构）
# ─────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_db():
    """测试前清空所有表（保留表结构）；测试后清空 MockMinio 存储。"""
    with _engine.connect() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
        conn.commit()
    _mock_minio._store.clear()
    yield
    # 测试后再清一次，确保下个测试干净
    with _engine.connect() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
        conn.commit()
    _mock_minio._store.clear()


# ─────────────────────────────────────────────
# db_session fixture
# ─────────────────────────────────────────────

@pytest.fixture
def db_session() -> Session:
    session = _TestSession()
    try:
        yield session
    finally:
        session.close()


# ─────────────────────────────────────────────
# FastAPI TestClient
# ─────────────────────────────────────────────

@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    def override_get_db():
        s = _TestSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


# ─────────────────────────────────────────────
# 图片文件工厂
# ─────────────────────────────────────────────

def make_png_bytes(width=10, height=10, color=(255, 0, 0)) -> bytes:
    from PIL import Image as PILImage
    img = PILImage.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def png_file_a():
    return ("test_a.png", make_png_bytes(color=(255, 0, 0)), "image/png")

@pytest.fixture
def png_file_b():
    return ("test_b.png", make_png_bytes(color=(0, 0, 255)), "image/png")


def create_task_in_db(db_session, name="测试任务", description="描述"):
    from models import Task
    import datetime
    t = Task(
        name=name, description=description, status="draft",
        created_at=datetime.datetime.utcnow(),
        updated_at=datetime.datetime.utcnow(),
    )
    db_session.add(t)
    db_session.commit()
    db_session.refresh(t)
    return t

@pytest.fixture
def existing_task(db_session):
    return create_task_in_db(db_session)
