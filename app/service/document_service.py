import hashlib
import uuid
from dataclasses import dataclass

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.document import Document, DocumentStatus
from app.models.document_chunk import DocumentChunk  # noqa: F401 确保建表
from app.models.user import User
from app.service import storage
from app.service.task_queue import enqueue_ingest_task
from app.models.kb_acl import AclPermission
from app.service import permission as perm_service

CHUNK_SIZE = 1024 * 1024  # 1MB 流式读取


@dataclass
class UploadResult:
    doc_id: uuid.UUID
    task_id: uuid.UUID | None
    status: DocumentStatus
    deduplicated: bool = False
    message: str = "文件已上传，正在后台解析"


async def _check_kb_permission(
    db: AsyncSession, user: User, kb_id: uuid.UUID, require_write: bool = True
) -> None:
    required = AclPermission.WRITE if require_write else AclPermission.READ
    # 直接复用统一权限校验，权限不足抛 403
    await perm_service.require_kb_permission(db, user, kb_id, required)

async def _read_and_hash(
    file: UploadFile,
) -> tuple[bytes, str, int]:
    """流式读取文件内容，同时计算 SHA256，并强制大小限制。

    返回 (文件内容, sha256, 大小)。生产环境大文件建议边读边写对象存储，
    这里为清晰起见先读入内存，配合 max_upload_size 限制。
    """
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    hasher = hashlib.sha256()
    buffer = bytearray()

    while True:
        chunk = await file.read(CHUNK_SIZE)
        if not chunk:
            break
        buffer.extend(chunk)
        hasher.update(chunk)
        if len(buffer) > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"文件超过 {settings.max_upload_size_mb}MB 限制",
            )

    if not buffer:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="上传文件为空",
        )

    return bytes(buffer), hasher.hexdigest(), len(buffer)


async def _find_duplicate(
    db: AsyncSession, kb_id: uuid.UUID, file_hash: str
) -> Document | None:
    """查同 kb + hash 的文档，不管软删与否。"""
    stmt = (
        select(Document)
        .where(
            Document.kb_id == kb_id,
            Document.file_hash == file_hash,
        )
        .order_by(Document.version.desc(), Document.created_at.desc())
    )
    return (await db.execute(stmt)).scalars().first()


async def upload_document(
    db: AsyncSession,
    user: User,
    kb_id: uuid.UUID,
    file: UploadFile,
) -> UploadResult:
    """上传文档主流程。

    步骤：
    1. 校验知识库写权限
    2. 校验 MIME 类型
    3. 流式读取 + 计算 hash + 大小限制
    4. 查重（秒传）
    5. 上传对象存储
    6. 落库 documents，status=uploaded
    7. 投递异步解析任务
    """

    # 1. 权限
    await _check_kb_permission(db, user, kb_id, require_write=True)

    # 2. MIME 校验
    content_type = file.content_type or "application/octet-stream"
    if content_type not in settings.allowed_mime_types:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"仅支持 {settings.allowed_mime_types}",
        )
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="仅支持 PDF 文件",
        )

    # 3. 读取 + hash + 大小限制
    data, file_hash, file_size = await _read_and_hash(file)

    # 4. 查重（秒传）
    existing = await _find_duplicate(db, kb_id, file_hash)
    # A. 已存在且有效且已入库 → 秒传
    if (
            existing
            and not existing.is_deleted
            and existing.status == DocumentStatus.INDEXED
    ):
        return UploadResult(
            doc_id=existing.id,
            task_id=None,
            status=existing.status,
            deduplicated=True,
            message="文件已存在，直接复用已入库文档",
        )

    doc_id = uuid.uuid4()
    object_key = storage.build_object_key(
        tenant_id=str(user.tenant_id),
        kb_id=str(kb_id),
        doc_id=str(doc_id),
        file_name=file.filename,
    )
    # B. 已存在但被软删 / 状态不是 indexed → 复用记录，重投任务
    if existing:
        # 重新上传文件到新 object_key
        try:
            storage.upload_bytes(object_key, data, content_type)
        except RuntimeError as e:
            raise HTTPException(502, str(e))

        existing.is_deleted = False
        existing.deleted_at = None
        existing.status = DocumentStatus.UPLOADED
        existing.error_msg = None
        existing.object_key = object_key
        existing.uploader_id = user.id
        db.add(existing)
        try:
            await db.commit()
            await db.refresh(existing)
        except Exception:
            await db.rollback()
            storage.delete_object(object_key)
            raise HTTPException(500, "文档记录恢复失败")

        task_id = enqueue_ingest_task(existing.id)
        return UploadResult(
            doc_id=existing.id,
            task_id=task_id,
            status=existing.status,
            message="已复用旧记录，正在重新解析",
        )

    # 5. 上传对象存储

    try:
        storage.upload_bytes(object_key, data, content_type)
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e),
        )

    # 6. 落库
    doc = Document(
        id=doc_id,
        tenant_id=user.tenant_id,
        kb_id=kb_id,
        uploader_id=user.id,
        file_name=file.filename,
        object_key=object_key,
        file_hash=file_hash,
        file_size=file_size,
        mime_type=content_type,
        status=DocumentStatus.UPLOADED,
    )
    db.add(doc)

    try:
        await db.commit()
        await db.refresh(doc)
    except Exception:
        await db.rollback()
        # 补偿：落库失败则删除刚上传的对象
        storage.delete_object(object_key)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="文档入库失败",
        )

    # 7. 投递异步任务
    task_id: uuid.UUID | None = None
    try:
        task_id = enqueue_ingest_task(doc.id)
    except Exception:
        # 任务投递失败，文档保留在 uploaded 状态，可由补偿任务重投
        doc.status = DocumentStatus.FAILED
        doc.error_msg = "解析任务投递失败"
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="任务队列不可用，请稍后重试",
        )

    return UploadResult(
        doc_id=doc.id,
        task_id=task_id,
        status=doc.status,
        message="文件已上传，正在后台解析",
    )


async def retry_document(
    db: AsyncSession, user: User, doc_id: uuid.UUID
) -> UploadResult:
    """重试解析：复用对象存储里已有的文件，重新投递解析任务。

    允许的状态：failed（解析失败）、uploaded（任务可能丢失）；
    正在处理中的状态会拒绝，已入库的文档需要先删除再重新上传。
    """
    doc = await db.get(Document, doc_id)
    if not doc or doc.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在"
        )

    await _check_kb_permission(db, user, doc.kb_id, require_write=True)

    in_progress = {
        DocumentStatus.PARSING,
        DocumentStatus.CHUNKING,
        DocumentStatus.EMBEDDING,
        DocumentStatus.INDEXING,
    }
    if doc.status in in_progress:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="文档正在处理中，请稍后再试"
        )
    if doc.status == DocumentStatus.INDEXED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="文档已入库，如需重新解析请先删除再上传",
        )

    doc.status = DocumentStatus.UPLOADED
    doc.error_msg = None
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    try:
        task_id = enqueue_ingest_task(doc.id)
    except Exception:
        doc.status = DocumentStatus.FAILED
        doc.error_msg = "解析任务投递失败"
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="任务队列不可用，请稍后重试",
        )

    return UploadResult(
        doc_id=doc.id,
        task_id=task_id,
        status=doc.status,
        message="已重新投递解析任务",
    )
