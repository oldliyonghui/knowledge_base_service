import uuid

import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.models.document import Document, DocumentStatus
from app.models.kb_acl import AclPermission
from app.models.user import User
from app.schemas.document import (
    DocumentListItem,
    DocumentListResponse,
    DocumentResponse,
    DocumentStatusResponse,
)
from app.service import permission as perm_service
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("/{doc_id}", response_model=DocumentResponse)
async def get_document(
    doc_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    """查文档详情。"""
    doc = await db.get(Document, doc_id)
    if not doc or doc.is_deleted:
        raise HTTPException(status_code=404, detail="文档不存在")

    # 权限校验：能不能读该文档所属的 kb
    await perm_service.require_kb_permission(
        db, current_user, doc.kb_id, AclPermission.READ
    )
    return DocumentResponse.model_validate(doc)


@router.get("/{doc_id}/status", response_model=DocumentStatusResponse)
async def get_document_status(
    doc_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentStatusResponse:
    """查文档处理状态，前端轮询这个。"""
    doc = await db.get(Document, doc_id)
    if not doc or doc.is_deleted:
        raise HTTPException(status_code=404, detail="文档不存在")

    await perm_service.require_kb_permission(
        db, current_user, doc.kb_id, AclPermission.READ
    )

    # 简单进度估算
    progress_map = {
        DocumentStatus.UPLOADED: 0.05,
        DocumentStatus.PARSING: 0.2,
        DocumentStatus.CHUNKING: 0.4,
        DocumentStatus.EMBEDDING: 0.6,
        DocumentStatus.INDEXING: 0.85,
        DocumentStatus.INDEXED: 1.0,
        DocumentStatus.FAILED: 0.0,
        DocumentStatus.DELETED: 0.0,
    }

    return DocumentStatusResponse(
        doc_id=doc.id,
        status=doc.status,
        progress=progress_map.get(doc.status, 0.0),
        error_msg=doc.error_msg,
        updated_at=doc.updated_at,
    )


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    kb_id: uuid.UUID | None = None,
    status_filter: DocumentStatus | None = None,
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentListResponse:
    """列文档，可按 kb 和状态过滤。"""
    from sqlalchemy import func

    base = select(Document).where(Document.is_deleted.is_(False))

    if kb_id:
        await perm_service.require_kb_permission(
            db, current_user, kb_id, AclPermission.READ
        )
        base = base.where(Document.kb_id == kb_id)
    else:
        # 没指定 kb 就查当前用户可读的所有 kb
        readable = await perm_service.list_readable_kb_ids(
            db, current_user, current_user.tenant_id
        )
        if not readable:
            return DocumentListResponse(total=0, page=page, page_size=page_size, items=[])
        base = base.where(Document.kb_id.in_(readable))

    if status_filter:
        base = base.where(Document.status == status_filter)

    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()

    rows = (
        await db.execute(
            base.order_by(Document.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    return DocumentListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[DocumentListItem.model_validate(d) for d in rows],
    )


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    doc_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """软删文档：标记 is_deleted，异步清理向量和文件。

    简单版本先只标记，向量清理可以投一个 celery 任务。
    """
    doc = await db.get(Document, doc_id)
    if not doc or doc.is_deleted:
        raise HTTPException(status_code=404, detail="文档不存在")

    await perm_service.require_kb_permission(
        db, current_user, doc.kb_id, AclPermission.WRITE
    )

    doc.is_deleted = True
    doc.deleted_at = datetime.now(timezone.utc)
    doc.status = DocumentStatus.DELETED
    db.add(doc)
    await db.commit()

    # TODO: 投递 celery 任务清理 Milvus 向量和 MinIO 文件
    # 投递异步清理任务
    try:
        from app.worker.tasks import delete_document as delete_task

        task = delete_task.delay(str(doc_id))
        logger.info("已投递删除任务 doc_id=%s task_id=%s", doc_id, task.id)
    except Exception as e:
        # 任务投递失败不阻塞返回；文档已软删，用户看不到
        # 后续可以靠定时补偿任务扫描 is_deleted=True 且 chunks 未清的文档重投
        logger.warning("删除任务投递失败 doc_id=%s err=%s", doc_id, e)