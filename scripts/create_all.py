# 建表脚本（本地调试一次性用）
import asyncio

from app.db.session import engine
from app.models import Base  # noqa: F401 必须 import 让所有模型注册


async def create_all() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    print("All tables created")


if __name__ == "__main__":
    asyncio.run(create_all())