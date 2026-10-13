import io
from functools import lru_cache

from minio import Minio
from minio.error import S3Error

from app.core.config import settings


@lru_cache
def get_minio_client() -> Minio:
    return Minio(
        endpoint=settings.s3_endpoint,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
        secure=settings.s3_secure,
    )


def ensure_bucket() -> None:
    client = get_minio_client()
    if not client.bucket_exists(settings.s3_bucket):
        client.make_bucket(settings.s3_bucket)


def upload_bytes(object_key: str, data: bytes, content_type: str) -> None:
    """把内存中的 bytes 上传到对象存储。

    适用于已限制大小的文件；大文件建议用流式 upload_stream。
    """
    client = get_minio_client()
    try:
        client.put_object(
            bucket_name=settings.s3_bucket,
            object_name=object_key,
            data=io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
    except S3Error as e:
        raise RuntimeError(f"对象存储上传失败: {e}") from e


def delete_object(object_key: str) -> None:
    client = get_minio_client()
    try:
        client.remove_object(settings.s3_bucket, object_key)
    except S3Error:
        # 删除失败不阻塞主流程，记录日志即可
        pass


def build_object_key(
    tenant_id: str, kb_id: str, doc_id: str, file_name: str
) -> str:
    """生成对象存储 key，按租户/知识库/文档分层，避免文件名冲突。"""
    safe_name = file_name.replace("/", "_").replace("\\", "_")
    return f"{tenant_id}/kbs/{kb_id}/docs/{doc_id}/{safe_name}"