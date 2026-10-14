import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.models.refresh_token import RefreshToken
from app.models.user import Role, User
from app.schemas.user import UserCreate, UserSelfUpdate, UserUpdate


async def get_user_or_404(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在"
        )
    return user


async def list_users(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[User], int]:
    """按租户 + 关键字（用户名/邮箱/姓名）分页查询，返回 (当前页数据, 总数)。"""
    conditions = []
    if tenant_id:
        conditions.append(User.tenant_id == tenant_id)
    if keyword and keyword.strip():
        pattern = f"%{keyword.strip()}%"
        conditions.append(
            or_(
                User.username.ilike(pattern),
                User.email.ilike(pattern),
                User.full_name.ilike(pattern),
            )
        )

    total_stmt = select(func.count()).select_from(User)
    list_stmt = select(User)
    if conditions:
        total_stmt = total_stmt.where(*conditions)
        list_stmt = list_stmt.where(*conditions)

    total = (await db.execute(total_stmt)).scalar_one()
    users = (
        await db.execute(
            list_stmt.order_by(User.username)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return list(users), total


async def reset_password(
    db: AsyncSession, user: User, new_password: str
) -> None:
    """
    管理员重置密码：改掉哈希，并吊销该用户所有未失效的 refresh token，
    强制其重新登录（与 auth_service.change_password 的处理一致）。
    """
    user.hashed_password = security.hash_password(new_password)
    db.add(user)

    stmt = select(RefreshToken).where(
        RefreshToken.user_id == user.id,
        RefreshToken.revoked.is_(False),
    )
    for rt in (await db.execute(stmt)).scalars().all():
        rt.revoked = True
        db.add(rt)

    await db.commit()


async def create_user(db: AsyncSession, payload: UserCreate) -> User:
    # 唯一性检查
    stmt = select(User).where(
        (User.username == payload.username)
        | (User.email == payload.email if payload.email else False)
    )
    if (await db.execute(stmt)).scalars().first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="用户名或邮箱已存在",
        )

    user = User(
        tenant_id=payload.tenant_id,
        dept_id=payload.dept_id,
        username=payload.username,
        email=payload.email,
        full_name=payload.full_name,
        hashed_password=security.hash_password(payload.password),
        is_active=payload.is_active,
        is_superuser=payload.is_superuser,
    )

    if payload.role_ids:
        roles = (
            await db.execute(select(Role).where(Role.id.in_(payload.role_ids)))
        ).scalars().all()
        user.roles = list(roles)

    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def update_user(
    db: AsyncSession, user: User, payload: UserUpdate
) -> User:
    data = payload.model_dump(exclude_unset=True)
    role_ids = data.pop("role_ids", None)

    for field, value in data.items():
        setattr(user, field, value)

    if role_ids is not None:
        roles = (
            await db.execute(select(Role).where(Role.id.in_(role_ids)))
        ).scalars().all()
        user.roles = list(roles)

    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def update_self(
    db: AsyncSession, user: User, payload: UserSelfUpdate
) -> User:
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(user, field, value)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user
