import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.kb_acl import (
    PERMISSION_LEVEL,
    AclPermission,
    AclSubjectType,
    KBAcl,
)


async def get_user_acl_grants(
    db: AsyncSession,
    user_id: uuid.UUID,
    dept_id: uuid.UUID | None,
    role_ids: list[uuid.UUID],
    kb_ids: list[uuid.UUID] | None = None,
) -> list[KBAcl]:
    """查出用户相关的所有 ACL 记录（user/dept/role 三类主体）。"""
    conditions = [
        (KBAcl.subject_type == AclSubjectType.USER)
        & (KBAcl.subject_id == user_id),
    ]
    if dept_id:
        conditions.append(
            (KBAcl.subject_type == AclSubjectType.DEPT)
            & (KBAcl.subject_id == dept_id)
        )
    if role_ids:
        conditions.append(
            (KBAcl.subject_type == AclSubjectType.ROLE)
            & (KBAcl.subject_id.in_(role_ids))
        )

    from sqlalchemy import or_

    stmt = select(KBAcl).where(or_(*conditions))
    if kb_ids:
        stmt = stmt.where(KBAcl.kb_id.in_(kb_ids))

    result = await db.execute(stmt)
    return list(result.scalars().all())

def list_acl_dept_role_ids_sync(
    session: Session, kb_id: uuid.UUID
) -> tuple[list[str], list[str]]:
    stmt = select(KBAcl).where(KBAcl.kb_id == kb_id)
    acls = session.execute(stmt).scalars().all()
    dept_ids = [
        str(a.subject_id)
        for a in acls
        if a.subject_type == AclSubjectType.DEPT
    ]
    role_ids = [
        str(a.subject_id)
        for a in acls
        if a.subject_type == AclSubjectType.ROLE
    ]
    return dept_ids, role_ids


def max_permission(acls: list[KBAcl]) -> AclPermission | None:
    """从一组 ACL 记录里取最高权限。"""
    if not acls:
        return None
    return max(acls, key=lambda a: PERMISSION_LEVEL[a.permission]).permission


def has_permission(
    current: AclPermission | None,
    required: AclPermission,
) -> bool:
    if current is None:
        return False
    return PERMISSION_LEVEL[current] >= PERMISSION_LEVEL[required]

def list_acl_dept_role_ids_sync(
    session: Session, kb_id: uuid.UUID
) -> tuple[list[str], list[str]]:
    stmt = select(KBAcl).where(KBAcl.kb_id == kb_id)
    acls = session.execute(stmt).scalars().all()
    dept_ids = [
        str(a.subject_id)
        for a in acls
        if a.subject_type == AclSubjectType.DEPT
    ]
    role_ids = [
        str(a.subject_id)
        for a in acls
        if a.subject_type == AclSubjectType.ROLE
    ]
    return dept_ids, role_ids