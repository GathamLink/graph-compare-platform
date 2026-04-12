"""
MinIO OSS 封装服务
- 上传文件，返回 oss_key
- 删除对象
- 生成公开访问 URL
- 确保 Bucket 存在并设置公开读策略
"""
import io
import json
import os
import uuid
from typing import Optional

from dotenv import load_dotenv
from fastapi import UploadFile
from minio import Minio
from minio.error import S3Error

load_dotenv()

_endpoint   = os.getenv("MINIO_ENDPOINT",   "localhost:13012")
_access_key = os.getenv("MINIO_ACCESS_KEY", "admin")
_secret_key = os.getenv("MINIO_SECRET_KEY", "password123")
BUCKET      = os.getenv("MINIO_BUCKET",     "graph-compare")

client = Minio(
    _endpoint,
    access_key=_access_key,
    secret_key=_secret_key,
    secure=False,
)

# 公开读 Bucket Policy（内网使用，无需鉴权）
_PUBLIC_POLICY = json.dumps({
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {"AWS": ["*"]},
            "Action": ["s3:GetObject"],
            "Resource": [f"arn:aws:s3:::{BUCKET}/*"],
        }
    ],
})


def ensure_bucket() -> None:
    """确保 Bucket 存在，不存在则创建并设置公开读"""
    try:
        if not client.bucket_exists(BUCKET):
            client.make_bucket(BUCKET)
            client.set_bucket_policy(BUCKET, _PUBLIC_POLICY)
    except S3Error as e:
        raise RuntimeError(f"MinIO bucket init failed: {e}") from e


async def upload_to_oss(file: UploadFile, prefix: str = "images") -> str:
    """
    上传 UploadFile 到 MinIO，返回 oss_key（格式：{prefix}/{uuid}.{ext}）
    """
    ensure_bucket()
    ext = os.path.splitext(file.filename or "")[1].lower() or ".bin"
    oss_key = f"{prefix}/{uuid.uuid4().hex}{ext}"
    data = await file.read()
    client.put_object(
        BUCKET,
        oss_key,
        data=io.BytesIO(data),
        length=len(data),
        content_type=file.content_type or "application/octet-stream",
    )
    return oss_key


def upload_bytes_to_oss(data: bytes, oss_key: str, content_type: str = "image/png") -> str:
    """
    上传 bytes 到 MinIO（差异图使用），返回 oss_key
    """
    ensure_bucket()
    client.put_object(
        BUCKET,
        oss_key,
        data=io.BytesIO(data),
        length=len(data),
        content_type=content_type,
    )
    return oss_key


def delete_from_oss(oss_key: Optional[str]) -> None:
    """删除 OSS 对象，key 为 None 时静默跳过"""
    if not oss_key:
        return
    try:
        client.remove_object(BUCKET, oss_key)
    except S3Error:
        pass  # 对象不存在时不报错


def get_public_url(oss_key: Optional[str]) -> Optional[str]:
    """
    拼接公开访问 URL：http://{endpoint}/{bucket}/{oss_key}
    """
    if not oss_key:
        return None
    return f"http://{_endpoint}/{BUCKET}/{oss_key}"


def is_minio_available() -> bool:
    """健康检查：MinIO 是否可访问"""
    try:
        client.list_buckets()
        return True
    except Exception:
        return False
