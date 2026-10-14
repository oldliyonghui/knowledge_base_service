import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import File, UploadFile
from app.schemas.document import DocumentUploadResponse
from app.service.document_service import upload_document
from app.core.deps import get_current_user, get_db
from app.models.kb_acl import AclPermission
from app.models.user import User
from app.schemas.kb_acl import (
    KBAclCreate,
    KBAclListResponse,
    KBAclResponse,
    KBAclUpdate,
    MyPermissions,
)
from app.schemas.knowledge_base import (
    KnowledgeBaseCreate,
    KnowledgeBaseDetail,
    KnowledgeBaseListResponse,
    KnowledgeBaseResponse,
    KnowledgeBaseUpdate,
)
from app.service import kb_service
from app.service import permission as perm_service

router = APIRouter(prefix="/kbs", tags=["knowledge-bases"])


@router.post(
    "",
    response_model=KnowledgeBaseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_kb(
    payload: KnowledgeBaseCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeBaseResponse:
    kb = await kb_service.create_kb(db, current_user, payload)
    return KnowledgeBaseResponse.model_validate(kb)


@router.get("", response_model=KnowledgeBaseListResponse)
async def list_my_kbs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeBaseListResponse:
    kb_ids = await perm_service.list_readable_kb_ids(
        db, current_user, current_user.tenant_id
    )
    return await kb_service.list_kbs(db, kb_ids, page, page_size)


@router.get("/{kb_id}", response_model=KnowledgeBaseDetail)
async def get_kb(
    kb_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeBaseDetail:
    kb, _, _ = await perm_service.require_kb_permission(
        db, current_user, kb_id, AclPermission.READ
    )
    detail = KnowledgeBaseDetail.model_validate(kb)
    counts = await kb_service.kb_counts(db, [kb.id])
    detail.doc_count, detail.chunk_count = counts.get(kb.id, (0, 0))
    return detail


@router.patch("/{kb_id}", response_model=KnowledgeBaseResponse)
async def update_kb(
    kb_id: uuid.UUID,
    payload: KnowledgeBaseUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeBaseResponse:
    kb, _, _ = await perm_service.require_kb_permission(
        db, current_user, kb_id, AclPermission.ADMIN
    )
    kb = await kb_service.update_kb(db, kb, payload)
    return KnowledgeBaseResponse.model_validate(kb)


@router.get("/{kb_id}/my-permission", response_model=MyPermissions)
async def my_permission(
    kb_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MyPermissions:
    return await perm_service.get_my_permission(db, current_user, kb_id)

@router.post(
    "/{kb_id}/documents/upload",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="上传 PDF 文档到知识库",
)
async def upload_kb_document(
    kb_id: uuid.UUID,
    file: UploadFile = File(..., description="PDF 文件"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentUploadResponse:
    """接收 PDF 文件并异步解析入库。

    接口本身只做鉴权、校验、存文件、落库、投递任务，
    解析 / 分块 / 向量化 / 写 Milvus 全部由异步 Worker 完成。
    """
    result = await upload_document(
        db=db, user=current_user, kb_id=kb_id, file=file
    )

    return DocumentUploadResponse(
        doc_id=result.doc_id,
        task_id=result.task_id,
        status=result.status,
        message=result.message,
        deduplicated=result.deduplicated,
    )

# ---------- ACL 管理 ----------
@router.get("/{kb_id}/acls", response_model=KBAclListResponse)
async def list_acls(
    kb_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> KBAclListResponse:
    await perm_service.require_kb_permission(
        db, current_user, kb_id, AclPermission.ADMIN
    )
    return await kb_service.list_acls(db, kb_id)


@router.post(
    "/{kb_id}/acls",
    response_model=KBAclResponse,
    status_code=status.HTTP_201_CREATED,
)
async def grant_acl(
    kb_id: uuid.UUID,
    payload: KBAclCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> KBAclResponse:
    await perm_service.require_kb_permission(
        db, current_user, kb_id, AclPermission.ADMIN
    )
    acl = await kb_service.upsert_acl(db, kb_id, payload, granted_by=current_user.id)
    return KBAclResponse.model_validate(acl)


@router.patch("/{kb_id}/acls/{acl_id}", response_model=KBAclResponse)
async def update_acl(
    kb_id: uuid.UUID,
    acl_id: uuid.UUID,
    payload: KBAclUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> KBAclResponse:
    await perm_service.require_kb_permission(
        db, current_user, kb_id, AclPermission.ADMIN
    )
    acl = await kb_service.update_acl(db, kb_id, acl_id, payload)
    return KBAclResponse.model_validate(acl)


@router.delete(
    "/{kb_id}/acls/{acl_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_acl(
    kb_id: uuid.UUID,
    acl_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await perm_service.require_kb_permission(
        db, current_user, kb_id, AclPermission.ADMIN
    )
    await kb_service.revoke_acl(db, kb_id, acl_id)


@router.delete(
    "/{kb_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除知识库（需要 ADMIN 权限）",
)
async def delete_kb(
    kb_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """删除知识库。

    - 权限：仅 owner 或 ADMIN 可删
    - 行为：软删 KB + 软删该 KB 下所有文档 + 异步清 Milvus/MinIO
    """
    await kb_service.delete_kb(db, current_user, kb_id)
