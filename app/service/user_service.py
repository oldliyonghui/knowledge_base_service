import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.models.user import Role, User
from app.schemas.user import UserCreate, UserSelfUpdate, UserUpdate


async def get_user_or_404(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在"
        )
    return user


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