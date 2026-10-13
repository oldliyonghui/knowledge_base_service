from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

# 异步引擎，供 FastAPI 使用
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,          # 本地调试时打印 SQL
    pool_pre_ping=True,           # 连接前 ping 一下，防止 MySQL 断连
    pool_size=10,
    max_overflow=20,
    pool_recycle=1800,            # MySQL 默认 8 小时断连，半小时回收一次
    future=True,
)

# 会话工厂
async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,       # commit 后对象仍可读，配合 response 序列化
    autoflush=False,
    autocommit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：每个请求一个 session。"""
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()