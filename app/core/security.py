import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.core.config import settings

_ph = PasswordHasher()

ALGORITHM = "HS256"


# ---------- 密码 ----------
def hash_password(plain: str) -> str:
    return _ph.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, plain)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def need_rehash(hashed: str) -> bool:
    return _ph.check_needs_rehash(hashed)


# ---------- JWT ----------
def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    role_codes: list[str],
    expires_minutes: int | None = None,
) -> str:
    exp_minutes = expires_minutes or settings.jwt_access_expire_minutes
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "tid": str(tenant_id),
        "roles": role_codes,
        "type": "access",
        "iat": _now(),
        "exp": _now() + timedelta(minutes=exp_minutes),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=ALGORITHM)


def create_refresh_token(
    user_id: uuid.UUID,
    expires_days: int | None = None,
) -> tuple[str, datetime]:
    """返回 (token, 过期时间)。token 只在响应里出现一次，库里存 hash。"""
    days = expires_days or settings.jwt_refresh_expire_days
    expires_at = _now() + timedelta(days=days)
    payload = {
        "sub": str(user_id),
        "type": "refresh",
        "iat": _now(),
        "exp": expires_at,
        "jti": str(uuid.uuid4()),
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=ALGORITHM)
    return token, expires_at


def decode_token(token: str) -> dict[str, Any]:
    """解析并校验 JWT，失败抛 jwt.PyJWTError。"""
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[ALGORITHM])


def hash_token(token: str) -> str:
    """refresh token 只存 sha256，防止库泄露即被利用。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()