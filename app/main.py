import uvicorn
from fastapi import FastAPI, Depends
from fastapi.exceptions import ValidationException
from fastapi.responses import JSONResponse
from fastapi import HTTPException
from contextlib import asynccontextmanager

from app.api import api_router
from app.core.config import settings
from app.core.exceptions import BizException, biz_exception_handler, http_exception_handler, validation_exception_handler
import logging
from app.bootstrap import bootstrap
import logging

from app.core.deps import get_current_superuser

logger = logging.getLogger(__name__)
from app.models.user import User

class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"

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

    get_index().build(docs)
    logger.info("BM25 索引加载完成，共 %d 条", len(docs))

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时
    if settings.debug and settings.bootstrap_enabled:
        from app.bootstrap import bootstrap
        await bootstrap()

    # 加载 BM25 索引
    if settings.rag_hybrid_enabled:
        await _load_bm25_index()

    yield

    # ---- 关闭 ----
    # 有需要清理的资源（redis、http client 等）放这里


app = FastAPI(title="My FastAPI App", debug=settings.debug, lifespan=lifespan)

app.add_exception_handler(BizException, biz_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
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
