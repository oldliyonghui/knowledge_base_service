import tempfile
import uuid
from pathlib import Path

from minio import S3Error

from app.core.config import settings
from app.models.document import Document, DocumentStatus
from app.models.document_chunk import DocumentChunk, VectorStatus
from app.service.storage import get_minio_client
from app.worker.celery_app import celery_app
from app.worker.db import session_scope
from app.worker.exceptions import (
    RecoverableIngestError,
    UnrecoverableIngestError,
)
from app.worker.pipeline.chunker import chunk_pages
from app.worker.pipeline.embedder import embed_texts
from app.worker.pipeline.pdf_parser import parse_pdf
from app.worker.pipeline.status import set_document_status
from app.service.kb_acl_service import list_acl_dept_role_ids_sync
import uuid
import logging
from datetime import datetime, timezone

from sqlalchemy import delete

from app.service import storage
from app.worker.pipeline import milvus_store
from sqlalchemy import select
from app.models.document import Document

logger = logging.getLogger(__name__)


@celery_app.task(
    name="ingest_document",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    autoretry_for=(RecoverableIngestError,),
    retry_backoff=True,
    retry_jitter=True,
)
def ingest_document(self, doc_id_str: str) -> dict:
    """文档入库主任务。

    流程：
    1. 加载文档记录，检查状态
    2. 下载 PDF 到本地临时目录
    3. 解析 → 分块
    4. 清理旧的 chunks（关系库 + Milvus），保证幂等
    5. 关系库落 chunks（vector_status=pending）
    6. embedding → 组装 Milvus record
    7. Milvus upsert
    8. 关系库更新 vector_status=indexed，documents.status=indexed
    9. 清理本地临时文件
    """
    doc_id = uuid.UUID(doc_id_str)

    with session_scope() as session:
        doc = session.get(Document, doc_id)
        if not doc:
            return {"doc_id": doc_id_str, "status": "not_found"}
        if doc.is_deleted:
            return {"doc_id": doc_id_str, "status": "deleted"}
        if doc.status == DocumentStatus.INDEXED:
            # 已入库，直接返回（除非你要支持 force reindex）
            return {"doc_id": doc_id_str, "status": "already_indexed"}

        object_key = doc.object_key
        file_name = doc.file_name
        kb_id = doc.kb_id
        tenant_id = doc.tenant_id
        version = doc.version

    # 1. 下载 PDF
    tmp_dir = Path(tempfile.mkdtemp(prefix="ingest_"))
    local_path = tmp_dir / f"{doc_id}.pdf"

    try:
        _download_object(object_key, local_path)

        # 2. 解析
        with session_scope() as session:
            set_document_status(session, doc_id, DocumentStatus.PARSING)

        parsed = parse_pdf(local_path)

        # 3. 分块
        with session_scope() as session:
            set_document_status(session, doc_id, DocumentStatus.CHUNKING)

        chunks = chunk_pages(parsed.pages)
        if not chunks:
            raise UnrecoverableIngestError("PDF 未解析出任何有效文本")

        # 4. 清理旧数据（幂等：重跑不会重复）
        milvus_store.delete_by_doc_id(doc_id)
        with session_scope() as session:
            session.execute(
                delete(DocumentChunk).where(DocumentChunk.doc_id == doc_id)
            )

        # 5. 落关系库
        chunk_records: list[dict] = []
        with session_scope() as session:
            for c in chunks:
                chunk_id = uuid.uuid4()
                session.add(
                    DocumentChunk(
                        chunk_id=chunk_id,
                        doc_id=doc_id,
                        kb_id=kb_id,
                        tenant_id=tenant_id,
                        chunk_index=c.chunk_index,
                        content=c.content,
                        token_count=c.token_count,
                        page_start=c.page_start,
                        page_end=c.page_end,
                        section_title=c.section_title,
                        vector_status=VectorStatus.PENDING,
                        embedding_model=settings.embedding_model,
                    )
                )
                chunk_records.append(
                    {
                        "chunk_id": chunk_id,
                        "content": c.content,
                        "chunk_index": c.chunk_index,
                        "page_start": c.page_start,
                        "page_end": c.page_end,
                        "section_title": c.section_title,
                    }
                )
            session.flush()

        # 6. embedding
        with session_scope() as session:
            set_document_status(session, doc_id, DocumentStatus.EMBEDDING)

        texts = [r["content"] for r in chunk_records]
        vectors = embed_texts(texts)
        if len(vectors) != len(chunk_records):
            raise RecoverableIngestError(
                f"向量数量不匹配: {len(vectors)} != {len(chunk_records)}"
            )

        # 7. 写 Milvus
        with session_scope() as session:
            acl_dept_ids, acl_role_ids = list_acl_dept_role_ids_sync(session, kb_id)
            set_document_status(session, doc_id, DocumentStatus.INDEXING)

        records = [
            milvus_store.build_record(
                chunk_id=r["chunk_id"],
                vector=vectors[i],
                content=r["content"],
                doc_id=doc_id,
                kb_id=kb_id,
                tenant_id=tenant_id,
                chunk_index=r["chunk_index"],
                page_start=r["page_start"],
                page_end=r["page_end"],
                section_title=r["section_title"],
                file_name=file_name,
                version=version,
                embedding_model=settings.embedding_model,
                # ACL 可以从 kb_acl 里取，此处略
                acl_dept_ids=[],
                acl_role_ids=[],
            )
            for i, r in enumerate(chunk_records)
        ]
        milvus_store.upsert_records(records)

        # 8. 更新关系库状态
        with session_scope() as session:
            session.execute(
                DocumentChunk.__table__.update()
                .where(DocumentChunk.doc_id == doc_id)
                .values(vector_status=VectorStatus.INDEXED, vector_dim=settings.embedding_dim)
            )
            doc = session.get(Document, doc_id)
            if doc:
                doc.page_count = parsed.page_count
                doc.chunk_count = len(chunks)
                doc.embedding_model = settings.embedding_model
                doc.status = DocumentStatus.INDEXED
                doc.error_msg = None
                session.add(doc)

        return {
            "doc_id": doc_id_str,
            "status": "indexed",
            "page_count": parsed.page_count,
            "chunk_count": len(chunks),
        }

    except UnrecoverableIngestError as e:
        _mark_failed(doc_id, str(e))
        return {"doc_id": doc_id_str, "status": "failed", "error": str(e)}

    except RecoverableIngestError as e:
        # 交给 Celery 重试，暂时标记为 failed，后续重试成功会覆盖
        _mark_failed(doc_id, f"retrying: {e}")
        raise self.retry(exc=e)

    except Exception as e:
        # 未知异常统一按可重试处理，超过 max_retries 后落 failed
        _mark_failed(doc_id, f"unexpected: {e}")
        raise self.retry(exc=RecoverableIngestError(str(e)))

    finally:
        # 9. 清理临时文件
        try:
            if local_path.exists():
                local_path.unlink()
            tmp_dir.rmdir()
        except OSError:
            pass


def _download_object(object_key: str, dest: Path) -> None:
    client = get_minio_client()
    try:
        resp = client.get_object(settings.s3_bucket, object_key)
        try:
            with open(dest, "wb") as f:
                for data in resp.stream(1024 * 1024):
                    f.write(data)
        finally:
            resp.close()
            resp.release_conn()
    except S3Error as e:
        if e.code == "NoSuchKey":
            raise UnrecoverableIngestError(
                f"MinIO 中文件不存在，object_key={object_key}，可能是重传时未上传文件"
            ) from e
        raise RecoverableIngestError(f"下载对象失败: {e}") from e
    except Exception as e:
        raise RecoverableIngestError(f"下载对象失败: {e}") from e


def _mark_failed(doc_id: uuid.UUID, msg: str) -> None:
    try:
        with session_scope() as session:
            set_document_status(session, doc_id, DocumentStatus.FAILED, error_msg=msg)
    except Exception:
        # 记录失败不阻塞任务返回
        pass

@celery_app.task(
    name="delete_document",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    autoretry_for=(RecoverableIngestError,),
    retry_backoff=True,
    retry_jitter=True,
)
def delete_document(self, doc_id_str: str) -> dict:
    """删除文档：
    1. Milvus 删向量
    2. 关系库硬删 document_chunks
    3. MinIO 删文件
    4. 关系库标记 documents.is_deleted = True

    幂等：重复执行不会报错，也不会有脏数据。
    """
    doc_id = uuid.UUID(doc_id_str)

    # 1. 取 object_key（不存在就说明已被硬删，直接返回）
    with session_scope() as session:
        doc = session.get(Document, doc_id)
        if not doc:
            return {"doc_id": doc_id_str, "status": "not_found"}
        object_key = doc.object_key

    # 2. 删 Milvus 向量（失败可重试）
    try:
        deleted_vectors = milvus_store.delete_by_doc_id(doc_id)
    except Exception as e:
        logger.exception("删除 Milvus 向量失败 doc_id=%s", doc_id)
        raise RecoverableIngestError(f"删除 Milvus 向量失败: {e}") from e

    # 3. 硬删 chunks（清空占用，便于审计用 documents 表即可）
    with session_scope() as session:
        session.execute(
            delete(DocumentChunk).where(DocumentChunk.doc_id == doc_id)
        )

    # 4. 删 MinIO 文件（失败只记日志，不阻塞；不重试）
    try:
        storage.delete_object(object_key)
    except Exception as e:
        logger.warning("删除 MinIO 对象失败 object_key=%s err=%s", object_key, e)

    # 5. 标记 documents 已删
    with session_scope() as session:
        doc = session.get(Document, doc_id)
        if doc:
            doc.is_deleted = True
            doc.deleted_at = datetime.now(timezone.utc)
            doc.status = DocumentStatus.DELETED
            doc.chunk_count = 0
            session.add(doc)

    logger.info(
        "文档已删除 doc_id=%s vectors=%d object_key=%s",
        doc_id, deleted_vectors, object_key,
    )
    return {
        "doc_id": doc_id_str,
        "status": "deleted",
        "deleted_vectors": deleted_vectors,
    }

@celery_app.task(
    name="cleanup_kb",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def cleanup_kb(self, kb_id_str: str) -> dict:
    """清理知识库的所有向量和文件。

    步骤：
    1. 从 Milvus 按 kb_id 删所有向量
    2. 从 MinIO 删该 KB 下所有文档的文件
    3. 关系库 document_chunks 已被 CASCADE 清空

    幂等：重复执行不会报错。
    """
    kb_id = uuid.UUID(kb_id_str)
    deleted_vectors = 0
    deleted_objects = 0

    # 1. 清 Milvus
    try:
        from app.worker.pipeline.milvus_store import get_client, COLLECTION_NAME

        c = get_client()
        res = c.delete(
            collection_name=COLLECTION_NAME,
            filter=f'kb_id == "{kb_id}"',
        )
        deleted_vectors = res.get("delete_count", 0)
        logger.info("Milvus 删除向量 kb_id=%s count=%s", kb_id, deleted_vectors)
    except Exception as e:
        logger.exception("Milvus 清理失败 kb_id=%s", kb_id)
        raise RecoverableIngestError(f"Milvus 清理失败: {e}") from e

    # 2. 清 MinIO（先查出所有 object_key）
    with session_scope() as session:
        rows = session.execute(
            select(Document.object_key)
            .where(Document.kb_id == kb_id)
        ).scalars().all()

    from app.service import storage
    for obj_key in rows:
        try:
            storage.delete_object(obj_key)
            deleted_objects += 1
        except Exception as e:
            logger.warning("删除对象失败 key=%s err=%s", obj_key, e)

    logger.info(
        "KB 清理完成 kb_id=%s vectors=%d objects=%d",
        kb_id, deleted_vectors, deleted_objects,
    )
    return {
        "kb_id": kb_id_str,
        "deleted_vectors": deleted_vectors,
        "deleted_objects": deleted_objects,
    }
