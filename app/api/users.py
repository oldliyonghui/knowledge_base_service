import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_superuser, get_current_user, get_db
from app.models.user import User
from app.schemas.user import (
    UserCreate,
    UserResponse,
    UserSelfUpdate,
    UserUpdate,
)
from app.service import user_service

router = APIRouter(prefix="/users", tags=["users"])


# ---------- 当前用户 ----------
@router.get("/me", response_model=UserResponse)
async def read_me(current_user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse.model_validate(current_user)


@router.patch("/me", response_model=UserResponse)
async def update_me(
    payload: UserSelfUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    user = await user_service.update_self(db, current_user, payload)
    return UserResponse.model_validate(user)


# ---------- 管理员 ----------
@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(get_current_superuser)],
)
async def create_user(
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    user = await user_service.create_user(db, payload)
    return UserResponse.model_validate(user)


@router.get(
    "",
    response_model=list[UserResponse],
    dependencies=[Depends(get_current_superuser)],
)
async def list_users(
    tenant_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[UserResponse]:
    stmt = select(User)
    if tenant_id:
        stmt = stmt.where(User.tenant_id == tenant_id)
    users = (await db.execute(stmt)).scalars().all()
    return [UserResponse.model_validate(u) for u in users]


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    dependencies=[Depends(get_current_superuser)],
)
async def get_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    user = await user_service.get_user_or_404(db, user_id)
    return UserResponse.model_validate(user)


@router.patch(
    "/{user_id}",
    response_model=UserResponse,
    dependencies=[Depends(get_current_superuser)],
)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    user = await user_service.get_user_or_404(db, user_id)
    user = await user_service.update_user(db, user, payload)
    return UserResponse.model_validate(user)