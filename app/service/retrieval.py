import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.schemas.document_chunk import ChunkCitation
from app.service.permission import build_milvus_acl_filter
from app.worker.pipeline.embedder import embed_texts
from app.worker.pipeline.milvus_store import COLLECTION_NAME, get_client
from app.core.config import settings
from app.service.reranker import rerank
from app.service.query_rewriter import rewrite_query
from app.service.bm25_index import get_index as get_bm25_index
from app.service.fusion import rrf_fusion

import logging
logger = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    chunk_id: uuid.UUID
    doc_id: uuid.UUID
    kb_id: uuid.UUID
    content: str
    score: float
    page_start: int | None
    page_end: int | None
    section_title: str | None
    file_name: str | None


def _embed_query(question: str) -> list[float]:
    # 复用 worker 的 embedder；单条查询
    vectors = embed_texts([question])
    return vectors[0]


def _milvus_search(
    query_vector: list[float],
    filter_expr: str,
    top_k: int,
) -> list[dict]:
    client = get_client()
    results = client.search(
        collection_name=COLLECTION_NAME,
        data=[query_vector],
        anns_field="vector",
        search_params={"metric_type": "COSINE", "params": {}},
        limit=top_k,
        filter=filter_expr,
        output_fields=[
            "chunk_id", "doc_id", "kb_id", "content",
            "chunk_index", "page_start", "page_end",
            "section_title", "file_name",
        ],
    )
    hits: list[dict] = []
    for hit in results[0]:
        e = hit.entity
        hits.append({
            "chunk_id": e.get("chunk_id"),
            "doc_id": e.get("doc_id"),
            "kb_id": e.get("kb_id"),
            "content": e.get("content"),
            "page_start": e.get("page_start"),
            "page_end": e.get("page_end"),
            "section_title": e.get("section_title"),
            "file_name": e.get("file_name"),
            "score": hit.score,
        })
    return hits


async def retrieve(
    db: AsyncSession,
    user,
    readable_kb_ids: list[uuid.UUID],
    question: str,
    top_k: int,
) -> list[RetrievedChunk]:
    """检索主流程：
    1. query 改写（可选）得到 N 个 query
    2. 每个 query 走向量检索（可选加 BM25）
    3. RRF 融合多路结果
    4. rerank 精排
    5. 回表补元数据
    """

    if not readable_kb_ids:
        return []

    filter_expr = build_milvus_acl_filter(
        tenant_id=user.tenant_id,
        readable_kb_ids=readable_kb_ids,
        user_dept_ids=[user.dept_id] if user.dept_id else None,
        user_role_ids=user.role_ids or None,
    )

    # ---------- 1. query 改写 ----------
    queries = rewrite_query(question)
    logger.info("检索 queries=%s", queries)

    coarse_k = max(top_k * 4, settings.rag_coarse_top_k)

    # ---------- 2. 多路召回 ----------
    vec_hit_lists: list[list[dict]] = []
    bm25_hit_lists: list[list[dict]] = []

    for q in queries:
        # 2.1 向量检索
        qvec = _embed_query(q)
        hits = _milvus_search(qvec, filter_expr, coarse_k)
        if hits:
            vec_hit_lists.append(hits)

        # 2.2 BM25 检索（如果开启）
        if settings.rag_hybrid_enabled:
            bm25_index = get_bm25_index()
            bm25_results = bm25_index.search(
                query=q,
                top_k=settings.rag_bm25_top_k,
                tenant_id=str(user.tenant_id),
                kb_ids=[str(k) for k in readable_kb_ids],
            )
            if bm25_results:
                # 转换成和 Milvus 一致的格式
                bm25_hits = [
                    {
                        "chunk_id": d.chunk_id,
                        "doc_id": d.doc_id,
                        "kb_id": d.kb_id,
                        "content": d.content,
                        "score": bm25_score,        # BM25 分数
                        "page_start": d.page_start,
                        "page_end": d.page_end,
                        "section_title": d.section_title,
                        "file_name": d.file_name,
                        "_source": "bm25",
                    }
                    for d, bm25_score in bm25_results
                ]
                bm25_hit_lists.append(bm25_hits)

    # ---------- 3. 融合 ----------
    all_lists = vec_hit_lists + bm25_hit_lists
    if not all_lists:
        return []

    # 只有一路，不需要融合
    if len(all_lists) == 1:
        candidates = all_lists[0]
    else:
        candidates = rrf_fusion(all_lists, k=settings.rag_rrf_k)

    # 粗排候选太多会拖慢 rerank
    candidates = candidates[:coarse_k]
    if not candidates:
        return []

    # ---------- 4. rerank 精排 ----------
    if settings.rag_rerank_enabled and len(candidates) > top_k:
        docs = [h["content"] for h in candidates]
        reranked = rerank(question, docs, top_n=top_k)
        hits = apply_rerank_filter(
            candidates, reranked, top_k, settings.rag_rerank_min_score
        )
    else:
        hits = candidates[:top_k]

    if not hits:
        return []

    # ---------- 5. 回表 ----------
    doc_ids = list({uuid.UUID(h["doc_id"]) for h in hits})
    stmt = select(Document.id).where(
        Document.id.in_(doc_ids),
        Document.is_deleted.is_(False),
    )
    valid_doc_ids = {str(x) for x in (await db.execute(stmt)).scalars().all()}

    chunks: list[RetrievedChunk] = []
    for h in hits:
        if h["doc_id"] not in valid_doc_ids:
            continue
        chunks.append(
            RetrievedChunk(
                chunk_id=uuid.UUID(h["chunk_id"]),
                doc_id=uuid.UUID(h["doc_id"]),
                kb_id=uuid.UUID(h["kb_id"]),
                content=h["content"],
                score=float(h.get("score") or 0),
                page_start=h.get("page_start") or None,
                page_end=h.get("page_end") or None,
                section_title=h.get("section_title") or None,
                file_name=h.get("file_name") or None,
            )
        )
    return chunks


def to_citations(chunks: list[RetrievedChunk]) -> list[ChunkCitation]:
    return [
        ChunkCitation(
            chunk_id=c.chunk_id,
            doc_id=c.doc_id,
            file_name=c.file_name,
            page_start=c.page_start,
            page_end=c.page_end,
            section_title=c.section_title,
            content=c.content,
            score=c.score,
        )
        for c in chunks
    ]

def apply_rerank_filter(
    hits: list[dict],
    reranked: list[tuple[int, float]],
    top_k: int,
    min_score: float,
) -> list[dict]:
    """rerank 后处理，生产代码和评估脚本共用。

    规则：
    1. rerank 失败 → 回退到 Milvus 顺序
    2. 最高分 < min_score → 返回空（文档里没相关内容）
    3. 相对阈值：最高分 × 0.7 与 min_score 取大
    4. 保底：门槛过了但全被砍，至少留第 1 条
    """
    if not reranked:
        return hits[:top_k]

    max_score = max(s for _, s in reranked)

    if max_score < min_score:
        return []

    threshold = max(max_score * 0.7, min_score)
    result = [hits[i] for i, s in reranked if s >= threshold]

    if not result:
        result = [hits[reranked[0][0]]]

    return result