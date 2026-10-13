from functools import lru_cache

from langchain_community.embeddings import DashScopeEmbeddings

from app.core.config import settings
from app.worker.exceptions import RecoverableIngestError

@lru_cache
def _get_embeddings() -> DashScopeEmbeddings:
    return DashScopeEmbeddings(
         # 必须，否则报错
        model=settings.embedding_model,
    )


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    emb = _get_embeddings()
    vectors: list[list[float]] = []
    batch_size = settings.embedding_batch_size
    try:
        for i in range(0, len(texts), batch_size):
            vectors.extend(emb.embed_documents(texts[i : i + batch_size]))
    except Exception as e:
        raise RecoverableIngestError(f"embedding 调用失败: {e}") from e
    return vectors


def embed_query(text: str) -> list[float]:
    emb = _get_embeddings()
    try:
        return emb.embed_query(text)
    except Exception as e:
        raise RecoverableIngestError(f"embedding 查询失败: {e}") from e