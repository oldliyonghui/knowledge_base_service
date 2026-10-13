import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.kb_acl import AclPermission
from app.models.knowledge_base import KBVisibility, KnowledgeBase
from app.models.user import User
from app.schemas.kb_acl import MyPermissions
from app.service import kb_acl_service
from sqlalchemy import or_, select

from app.models.kb_acl import AclSubjectType
from app.models.knowledge_base import KBVisibility
from app.models.kb_acl import KBAcl


async def resolve_kb_permission(
    db: AsyncSession,
    user: User,
    kb: KnowledgeBase,
) -> tuple[AclPermission | None, str]:
    """计算用户对某知识库的最终权限。

    优先级：owner > ACL(user) > ACL(role) > ACL(dept) > visibility > none
    返回 (最高权限 or None, 来源说明)
    """
    # 1. owner 拥有最高权限
    if kb.owner_id == user.id:
        return AclPermission.ADMIN, "owner"

    # 2. 查出用户相关 ACL
    grants = await kb_acl_service.get_user_acl_grants(
        db=db,
        user_id=user.id,
        dept_id=user.dept_id,
        role_ids=user.role_ids,
        kb_ids=[kb.id],
    )
    if grants:
        # 主体优先级：user > role > dept（具体授权 > 角色 > 部门）
        for stype, reason in (
            ("user", "acl:user"),
            ("role", "acl:role"),
            ("dept", "acl:dept"),
        ):
            matched = [g for g in grants if g.subject_type.value == stype]
            if matched:
                return kb_acl_service.max_permission(matched), reason

    # 3. 可见性兜底
    if kb.visibility == KBVisibility.TENANT and kb.tenant_id == user.tenant_id:
        return AclPermission.READ, "visibility:tenant"
    if kb.visibility == KBVisibility.PUBLIC:
        return AclPermission.READ, "visibility:public"

    return None, "none"


async def require_kb_permission(
    db: AsyncSession,
    user: User,
    kb_id: uuid.UUID,
    required: AclPermission,
) -> tuple[KnowledgeBase, AclPermission, str]:
    """校验并返回 (知识库, 实际权限, 来源)，不通过直接抛异常。"""
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb or kb.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="知识库不存在或无权访问",
        )
    if kb.tenant_id != user.tenant_id and not user.is_superuser:
        # 跨租户一律不可见（超管除外）
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="知识库不存在或无权访问",
        )

    current, reason = await resolve_kb_permission(db, user, kb)
    if not kb_acl_service.has_permission(current, required):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"缺少 {required.value} 权限",
        )
    return kb, current, reason


async def get_my_permission(
    db: AsyncSession,
    user: User,
    kb_id: uuid.UUID,
) -> MyPermissions:
    kb = await db.get(KnowledgeBase, kb_id)
    if not kb or kb.is_deleted:
        return MyPermissions(
            kb_id=kb_id,
            can_read=False,
            can_write=False,
            can_admin=False,
            reason="not_found",
        )
    if kb.tenant_id != user.tenant_id and not user.is_superuser:
        return MyPermissions(
            kb_id=kb_id,
            can_read=False,
            can_write=False,
            can_admin=False,
            reason="cross_tenant",
        )

    current, reason = await resolve_kb_permission(db, user, kb)
    return MyPermissions(
        kb_id=kb_id,
        can_read=kb_acl_service.has_permission(current, AclPermission.READ),
        can_write=kb_acl_service.has_permission(current, AclPermission.WRITE),
        can_admin=kb_acl_service.has_permission(current, AclPermission.ADMIN),
        reason=reason,
    )


async def list_readable_kb_ids(
    db: AsyncSession,
    user: User,
    tenant_id: uuid.UUID,
) -> list[uuid.UUID]:
    """列出用户可读的所有知识库 ID，用于构造 Milvus 过滤条件。"""
    if user.is_superuser:
        stmt = select(KnowledgeBase.id).where(
            KnowledgeBase.tenant_id == tenant_id,
            KnowledgeBase.is_deleted.is_(False),
        )
        return list((await db.execute(stmt)).scalars().all())

    # 1. owner
    owner_stmt = select(KnowledgeBase.id).where(
        KnowledgeBase.tenant_id == tenant_id,
        KnowledgeBase.is_deleted.is_(False),
        KnowledgeBase.owner_id == user.id,
    )
    kb_ids = set((await db.execute(owner_stmt)).scalars().all())

    # 2. visibility = tenant / public
    vis_stmt = select(KnowledgeBase.id).where(
        KnowledgeBase.tenant_id == tenant_id,
        KnowledgeBase.is_deleted.is_(False),
        KnowledgeBase.visibility.in_([KBVisibility.TENANT, KBVisibility.PUBLIC]),
    )
    kb_ids.update((await db.execute(vis_stmt)).scalars().all())

    # 3. ACL 授权
    conditions = [
        (KBAcl.subject_type == AclSubjectType.USER)
        & (KBAcl.subject_id == user.id),
    ]
    if user.dept_id:
        conditions.append(
            (KBAcl.subject_type == AclSubjectType.DEPT)
            & (KBAcl.subject_id == user.dept_id)
        )
    if user.role_ids:
        conditions.append(
            (KBAcl.subject_type == AclSubjectType.ROLE)
            & (KBAcl.subject_id.in_(user.role_ids))
        )

    acl_stmt = select(KBAcl.kb_id).where(
        KBAcl.tenant_id == tenant_id,
        or_(*conditions),
    )
    kb_ids.update((await db.execute(acl_stmt)).scalars().all())

    return list(kb_ids)

# app/services/permission.py（追加）

def build_milvus_acl_filter(
    tenant_id: uuid.UUID,
    readable_kb_ids: list[uuid.UUID],
    user_dept_ids: list[uuid.UUID] | None = None,
    user_role_ids: list[uuid.UUID] | None = None,
) -> str:
    """构造 Milvus 检索时的过滤表达式。

    tenant_id + kb_id 硬隔离
    """
    if not readable_kb_ids:
        # 无任何可读 kb，用一个永假条件阻止召回
        return 'tenant_id == "__none__"'
    kb_arr = ", ".join(f'"{k}"' for k in readable_kb_ids)
    return f'tenant_id == "{tenant_id}" and kb_id in [{kb_arr}]'