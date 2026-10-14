import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.config import settings
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.schemas.auth import LoginResponse, TokenPair
from app.schemas.user import UserResponse


async def _get_user_by_identifier(
    db: AsyncSession, identifier: str
) -> User | None:
    stmt = select(User).where(
        (User.username == identifier) | (User.email == identifier)
    )
    result = await db.execute(stmt)
    return result.scalars().first()


async def _issue_tokens(
    db: AsyncSession,
    user: User,
    user_agent: str | None = None,
    ip: str | None = None,
) -> TokenPair:
    access = security.create_access_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        role_codes=user.role_codes,
    )
    refresh, expires_at = security.create_refresh_token(user_id=user.id)

    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=security.hash_token(refresh),
            expires_at=expires_at,
            user_agent=user_agent,
            ip=ip,
        )
    )
    await db.flush()

    return TokenPair(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.jwt_access_expire_minutes * 60,
    )


async def login(
    db: AsyncSession,
    username: str,
    password: str,
    user_agent: str | None = None,
    ip: str | None = None,
) -> LoginResponse:
    user = await _get_user_by_identifier(db, username)

    # 统一错误信息，避免枚举用户名
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="用户名或密码错误",
    )

    if not user:
        raise invalid
    if not security.verify_password(password, user.hashed_password):
        raise invalid
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="账号已禁用"
        )

    # 密码哈希升级
    if security.need_rehash(user.hashed_password):
        user.hashed_password = security.hash_password(password)

    user.last_login_at = datetime.now(timezone.utc)
    db.add(user)

    tokens = await _issue_tokens(db, user, user_agent=user_agent, ip=ip)
    await db.commit()
    await db.refresh(user)

    return LoginResponse(
        **tokens.model_dump(),
        user=UserResponse.model_validate(user),
    )


async def refresh_tokens(
    db: AsyncSession,
    refresh_token: str,
    user_agent: str | None = None,
    ip: str | None = None,
) -> TokenPair:
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="refresh_token 无效或已过期",
    )

    try:
        payload = security.decode_token(refresh_token)
    except Exception:
        raise invalid

    if payload.get("type") != "refresh":
        raise invalid

    token_hash = security.hash_token(refresh_token)
    stmt = select(RefreshToken).where(
        RefreshToken.token_hash == token_hash,
        RefreshToken.revoked.is_(False),
    )
    record = (await db.execute(stmt)).scalars().first()

    # 模型层统一返回带时区的 UTC 时间（UtcDateTime），这里直接和 aware 的当前时间比较
    if not record or record.expires_at < datetime.now(timezone.utc):
        raise invalid

    user = await db.get(User, record.user_id)
    if not user or not user.is_active:
        raise invalid

    # 轮换：旧的作废，换新的
    record.revoked = True
    db.add(record)

    tokens = await _issue_tokens(db, user, user_agent=user_agent, ip=ip)
    await db.commit()
    return tokens


async def logout(db: AsyncSession, refresh_token: str) -> None:
    token_hash = security.hash_token(refresh_token)
    stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    record = (await db.execute(stmt)).scalars().first()
    if record and not record.revoked:
        record.revoked = True
        db.add(record)
        await db.commit()


async def change_password(
    db: AsyncSession, user: User, old_password: str, new_password: str
) -> None:
    if not security.verify_password(old_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="原密码错误",
        )
    if old_password == new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="新密码不能与原密码相同",
        )

    user.hashed_password = security.hash_password(new_password)
    db.add(user)

    # 改动密码后吊销所有 refresh token，强制重新登录
    stmt = select(RefreshToken).where(
        RefreshToken.user_id == user.id,
        RefreshToken.revoked.is_(False),
    )
    for rt in (await db.execute(stmt)).scalars().all():
        rt.revoked = True
        db.add(rt)

    await db.commit()
