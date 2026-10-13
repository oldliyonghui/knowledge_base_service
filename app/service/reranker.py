# app/service/reranker.py
from functools import lru_cache
from dashscope import TextReRank
from app.core.config import settings


@lru_cache
def _rerank_model():
    return None  # 通义 rerank 无需 client


def rerank(query: str, documents: list[str], top_n: int = 5) -> list[tuple[int, float]]:
    """返回 [(原索引, 得分)]，按得分降序。"""
    resp = TextReRank.call(
        model=settings.rag_rerank_model,
        query=query,
        documents=documents,
        top_n=top_n,
        return_documents=False,
        api_key=settings.dashscope_api_key,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"rerank 失败: {resp.message} code: {resp.status_code}")

    results = resp.output.results
    # 通义返回的 index 是原始顺序的索引
    return [(r.index, r.relevance_score) for r in results]