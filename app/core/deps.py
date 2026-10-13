import uuid
from typing import AsyncGenerator

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.db.session import async_session_factory, get_db
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    cred_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无效的凭证",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = security.decode_token(token)
    except Exception as e:
        print("=" * 60, flush=True)
        print("[get_current_user] decode 失败:", type(e).__name__, repr(e), flush=True)
        print("[get_current_user] token 总长度:", len(token), flush=True)
        print("[get_current_user] 点数(应为 2):", token.count("."), flush=True)
        print("[get_current_user] 完整 token:", repr(token), flush=True)
        parts = token.split(".")
        for i, p in enumerate(parts):
            print(f"[get_current_user] part[{i}] 长度={len(p)}", flush=True)
        print("=" * 60, flush=True)
        raise cred_exc
    print("[get_current_user] payload:", payload, flush=True)

    if payload.get("type") != "access":
        print("[get_current_user] type 不是 access:", payload.get("type"), flush=True)
        raise cred_exc

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError):
        raise cred_exc

    user = await db.get(User, user_id)
    if not user:
        raise cred_exc
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="账号已禁用"
        )
    return user


async def get_current_superuser(
    user: User = Depends(get_current_user),
) -> User:
    if not user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限"
        )
    return user