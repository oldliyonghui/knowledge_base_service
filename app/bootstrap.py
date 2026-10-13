import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.config import settings
from app.models.user import Role, User

logger = logging.getLogger(__name__)


async def ensure_roles(db: AsyncSession) -> dict[str, Role]:
    """确保基础角色存在，返回 {code: Role}。"""
    wanted = {
        "admin": "系统管理员",
        "user": "普通用户",
    }
    result: dict[str, Role] = {}

    for code, name in wanted.items():
        role = (
            await db.execute(select(Role).where(Role.code == code))
        ).scalars().first()
        if not role:
            role = Role(code=code, name=name)
            db.add(role)
            await db.flush()
        result[code] = role

    return result


async def ensure_admin_user(db: AsyncSession) -> None:
    """确保初始管理员存在。已存在则跳过，不覆盖密码。"""
    exists = (
        await db.execute(
            select(User).where(User.username == settings.bootstrap_admin_username)
        )
    ).scalars().first()
    if exists:
        logger.info("初始管理员已存在，跳过: %s", exists.username)
        return

    roles = await ensure_roles(db)
    tenant_id = uuid.UUID(settings.bootstrap_tenant_id)

    admin = User(
        tenant_id=tenant_id,
        username=settings.bootstrap_admin_username,
        email=settings.bootstrap_admin_email,
        full_name=settings.bootstrap_admin_full_name,
        hashed_password=security.hash_password(settings.bootstrap_admin_password),
        is_active=True,
        is_superuser=True,
    )
    admin.roles = [roles["admin"]]

    db.add(admin)
    await db.commit()
    logger.warning(
        "已创建初始管理员: %s / %s（请尽快修改密码）",
        settings.bootstrap_admin_username,
        settings.bootstrap_admin_password,
    )


async def bootstrap() -> None:
    """应用启动时的初始化入口。"""
    if not settings.debug or not settings.bootstrap_enabled:
        return

    # 延迟 import，避免循环依赖
    from app.db.session import async_session_factory

    async with async_session_factory() as db:
        try:
            await ensure_admin_user(db)
        except Exception:
            await db.rollback()
            logger.exception("bootstrap 失败")