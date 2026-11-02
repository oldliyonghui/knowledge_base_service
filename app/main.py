import asyncio
import logging
from contextlib import asynccontextmanager, suppress

import uvicorn
from fastapi import Depends, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError, ValidationException
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.core.config import settings
from app.core.deps import get_current_superuser
from app.core.exceptions import (
    BizException,
    biz_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from app.models.user import User

logger = logging.getLogger(__name__)

# BM25 索引自动对账周期（秒）
_BM25_SYNC_INTERVAL = 30

logging.basicConfig(
    level=logging.INFO if not settings.debug else logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

async def _load_bm25_index():
    """从 MySQL 加载所有 chunk 到 BM25 索引。"""
    from sqlalchemy import select
    from app.db.session import async_session_factory
    from app.models.document import Document
    from app.models.document_chunk import DocumentChunk
    from app.service.bm25_index import BM25Doc, get_index

    async with async_session_factory() as db:
        stmt = (
            select(
                DocumentChunk.chunk_id,
                DocumentChunk.content,
                DocumentChunk.doc_id,
                DocumentChunk.kb_id,
                DocumentChunk.tenant_id,
                DocumentChunk.page_start,
                DocumentChunk.page_end,
                DocumentChunk.section_title,
                Document.file_name,
            )
            .join(Document, Document.id == DocumentChunk.doc_id)
            .where(
                DocumentChunk.is_deleted.is_(False),
                Document.is_deleted.is_(False),
            )
        )
        rows = (await db.execute(stmt)).all()

    docs = [
        BM25Doc(
            chunk_id=str(r.chunk_id),
            content=r.content,
            doc_id=str(r.doc_id),
            kb_id=str(r.kb_id),
            tenant_id=str(r.tenant_id),
            page_start=r.page_start,
            page_end=r.page_end,
            section_title=r.section_title,
            file_name=r.file_name,
        )
        for r in rows
    ]

    await asyncio.to_thread(get_index().build, docs)
    logger.info("BM25 索引加载完成，共 %d 条", len(docs))


async def _chunk_fingerprint() -> tuple[int, str | None]:
    """chunk 集合的廉价指纹：数量 + 最新创建时间。

    新增或硬删除 chunk 都会让它变化；chunk 内容不会原地修改。
    """
    from sqlalchemy import func, select
    from app.db.session import async_session_factory
    from app.models.document import Document
    from app.models.document_chunk import DocumentChunk

    async with async_session_factory() as db:
        stmt = (
            select(
                func.count(DocumentChunk.chunk_id),
                func.max(DocumentChunk.created_at),
            )
            .join(Document, Document.id == DocumentChunk.doc_id)
            .where(
                DocumentChunk.is_deleted.is_(False),
                Document.is_deleted.is_(False),
            )
        )
        count, latest = (await db.execute(stmt)).one()

    return int(count or 0), latest.isoformat() if latest else None


async def _bm25_autosync(interval: int = _BM25_SYNC_INTERVAL) -> None:
    """后台对账：chunk 集合变了就重建 BM25 索引。

    Celery worker 是独立进程，写库后无法直接更新 API 进程内的内存索引，
    所以用轮询兜底。数据量 <10 万时全量重建足够。
    """
    try:
        last = await _chunk_fingerprint()
    except Exception:
        last = None

    while True:
        try:
            fp = await _chunk_fingerprint()
            if fp != last:
                logger.info("检测到 chunk 集合变化 %s -> %s，重建 BM25 索引", last, fp)
                await _load_bm25_index()
                last = fp
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("BM25 自动同步失败，%d 秒后重试", interval)
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时
    if settings.debug and settings.bootstrap_enabled:
        from app.bootstrap import bootstrap
        await bootstrap()

    sync_task = None
    if settings.rag_hybrid_enabled:
        await _load_bm25_index()
        sync_task = asyncio.create_task(_bm25_autosync())

    yield

    # ---- 关闭 ----
    if sync_task:
        sync_task.cancel()
        with suppress(asyncio.CancelledError):
            await sync_task


app = FastAPI(title="My FastAPI App", debug=settings.debug, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(BizException, biz_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
# 参数校验失败实际抛的是 RequestValidationError（ValidationException 不是它的父类），
# 只注册 ValidationException 时 422 会绕过统一信封、返回裸 {"detail": [...]}。
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(ValidationException, validation_exception_handler)

#api路由
app.include_router(api_router)


# app/api/admin.py 或加在现有路由
@app.post("/admin/reload-bm25")
async def reload_bm25(current_user: User = Depends(get_current_superuser)):
    await _load_bm25_index()
    return {"status": "ok"}
@app.get("/")
async def root():
    return {"message": "Hello 123"}

@app.get("/hello/{name}")
async def say_hello(name: str):
    return {"message": f"Hello {name}"}


if __name__ == "__main__":
    #启动
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
