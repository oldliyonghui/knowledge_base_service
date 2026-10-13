# scripts/test_rerank.py
from app.service.retrieval import _embed_query, _milvus_search
from app.service.reranker import rerank

question = "扫地机器人外出时如何使用更安全"
query_vector = _embed_query(question)
filter_expr = 'tenant_id == "00000000-0000-0000-0000-000000000001"'

hits = _milvus_search(query_vector, filter_expr, 30)
docs = [h["content"] for h in hits]
reranked = rerank(question, docs, top_n=10)

print("=== rerank top 10 ===")
for orig_idx, score in reranked:
    h = hits[orig_idx]
    print(f"  rerank={score:.3f} cosine={h['score']:.3f}  {h['content'][:50]}")