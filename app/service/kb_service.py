import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.kb_acl import KBAcl
from app.models.knowledge_base import KnowledgeBase
from app.models.user import User
from app.schemas.kb_acl import KBAclCreate, KBAclListResponse, KBAclResponse, KBAclUpdate
from app.schemas.knowledge_base import (
    KnowledgeBaseCreate,
    KnowledgeBaseListResponse,
    KnowledgeBaseResponse,
    KnowledgeBaseUpdate,
)
from datetime import datetime, timezone

from app.models.document import Document, DocumentStatus
from app.models.kb_acl import AclPermission
from app.service import permission as perm_service
import logging
logger = logging.getLogger(__name__)


async def create_kb(
    db: AsyncSession, user: User, payload: KnowledgeBaseCreate
) -> KnowledgeBase:
    # 同名检查
    stmt = select(KnowledgeBase).where(
        KnowledgeBase.tenant_id == user.tenant_id,
        KnowledgeBase.name == payload.name,
        KnowledgeBase.is_deleted.is_(False),
    )
    if (await db.execute(stmt)).scalars().first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="知识库名称已存在"
        )

    kb = KnowledgeBase(
        tenant_id=user.tenant_id,
        owner_id=user.id,
        name=payload.name,
        description=payload.description,
        visibility=payload.visibility,
        embedding_model=payload.embedding_model,
        embedding_dim=payload.embedding_dim,
        chunk_size=payload.chunk_size,
        chunk_overlap=payload.chunk_overlap,
    )
    db.add(kb)
    await db.flush()

    for acl_in in payload.acls:
        db.add(
            KBAcl(
                kb_id=kb.id,
                tenant_id=user.tenant_id,
                subject_type=acl_in.subject_type,
                subject_id=acl_in.subject_id,
                permission=acl_in.permission,
                granted_by=user.id,
            )
        )

    await db.commit()
    await db.refresh(kb)
    return kb


async def update_kb(
    db: AsyncSession, kb: KnowledgeBase, payload: KnowledgeBaseUpdate
) -> KnowledgeBase:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(kb, field, value)
    db.add(kb)
    await db.commit()
    await db.refresh(kb)
    return kb


async def list_kbs(
    db: AsyncSession,
    kb_ids: list[uuid.UUID],
    page: int,
    page_size: int,
) -> KnowledgeBaseListResponse:
    if not kb_ids:
        return KnowledgeBaseListResponse(total=0, page=page, page_size=page_size, items=[])

    base = select(KnowledgeBase).where(
        KnowledgeBase.id.in_(kb_ids),
        KnowledgeBase.is_deleted.is_(False),
    )
    total = (
        await db.execute(
            select(func.count()).select_from(base.subquery())
        )
    ).scalar_one()

    rows = (
        await db.execute(
            base.order_by(KnowledgeBase.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    counts = await kb_counts(db, [k.id for k in rows])
    items = []
    for kb in rows:
        item = KnowledgeBaseResponse.model_validate(kb)
        item.doc_count, item.chunk_count = counts.get(kb.id, (0, 0))
        items.append(item)

    return KnowledgeBaseListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=items,
    )


async def kb_counts(
    db: AsyncSession, kb_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, int]]:
    """实时统计知识库的文档数与片段数。

    KnowledgeBase.doc_count / chunk_count 只在创建时写成 0、之后没有任何地方维护，
    直接返回会一直是 0，所以列表和详情都按文档表实时算。
    """
    if not kb_ids:
        return {}

    stmt = (
        select(
            Document.kb_id,
            func.count(Document.id),
            func.coalesce(func.sum(Document.chunk_count), 0),
        )
        .where(
            Document.kb_id.in_(kb_ids),
            Document.is_deleted.is_(False),
        )
        .group_by(Document.kb_id)
    )
    rows = (await db.execute(stmt)).all()
    return {row[0]: (int(row[1]), int(row[2])) for row in rows}
async def delete_kb(
    db: AsyncSession,
    user: User,
    kb_id: uuid.UUID,
) -> None:
    """删除知识库：软删 KB + 软删该 KB 下所有文档 + 投递清理任务。

    权限要求：ADMIN
    """
    # 1. 权限校验
    kb, _, _ = await perm_service.require_kb_permission(
        db, user, kb_id, AclPermission.ADMIN
    )

    now = datetime.now(timezone.utc)

    # 2. 软删该 KB 下所有文档
    from sqlalchemy import update

    await db.execute(
        update(Document)
        .where(Document.kb_id == kb_id, Document.is_deleted.is_(False))
        .values(
            is_deleted=True,
            deleted_at=now,
            status=DocumentStatus.DELETED,
        )
    )

    # 3. 软删 KB
    kb.is_deleted = True
    kb.deleted_at = now
    kb.doc_count = 0
    kb.chunk_count = 0
    db.add(kb)
    await db.commit()

    # 4. 投递异步清理任务
    try:
        from app.worker.tasks import cleanup_kb

        task = cleanup_kb.delay(str(kb_id))
        logger.info("已投递 KB 清理任务 kb_id=%s task_id=%s", kb_id, task.id)
    except Exception as e:
        # 清理任务投递失败不阻塞返回
        logger.warning("KB 清理任务投递失败 kb_id=%s err=%s", kb_id, e)

# ---------- ACL ----------
async def list_acls(db: AsyncSession, kb_id: uuid.UUID) -> KBAclListResponse:
    stmt = select(KBAcl).where(KBAcl.kb_id == kb_id)
    rows = (await db.execute(stmt)).scalars().all()
    return KBAclListResponse(
        total=len(rows),
        items=[KBAclResponse.model_validate(r) for r in rows],
    )


async def upsert_acl(
    db: AsyncSession,
    kb_id: uuid.UUID,
    payload: KBAclCreate,
    granted_by: uuid.UUID,
) -> KBAcl:
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")

    stmt = select(KBAcl).where(
        KBAcl.kb_id == kb_id,
        KBAcl.subject_type == payload.subject_type,
        KBAcl.subject_id == payload.subject_id,
    )
    acl = (await db.execute(stmt)).scalars().first()

    if acl:
        acl.permission = payload.permission
        acl.granted_by = granted_by
    else:
        acl = KBAcl(
            kb_id=kb_id,
            tenant_id=kb.tenant_id,
            subject_type=payload.subject_type,
            subject_id=payload.subject_id,
            permission=payload.permission,
            granted_by=granted_by,
        )
        db.add(acl)

    await db.commit()
    await db.refresh(acl)
    return acl


async def update_acl(
    db: AsyncSession,
    kb_id: uuid.UUID,
    acl_id: uuid.UUID,
    payload: KBAclUpdate,
) -> KBAcl:
    acl = await db.get(KBAcl, acl_id)
    if not acl or acl.kb_id != kb_id:
        raise HTTPException(status_code=404, detail="ACL 不存在")
    acl.permission = payload.permission
    db.add(acl)
    await db.commit()
    await db.refresh(acl)
    return acl


async def revoke_acl(
    db: AsyncSession, kb_id: uuid.UUID, acl_id: uuid.UUID
) -> None:
    acl = await db.get(KBAcl, acl_id)
    if not acl or acl.kb_id != kb_id:
        raise HTTPException(status_code=404, detail="ACL 不存在")
    await db.delete(acl)
    await db.commit()
