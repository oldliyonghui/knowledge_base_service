

from typing import Any
from pymilvus import MilvusClient

from app.vector_store.milvus_schema import COLLECTION_NAME
from pymilvus import AnnSearchRequest

def build_acl_filter(
    tenant_id: str,
    kb_ids: list[str],
    dept_ids: list[str] | None = None,
    role_ids: list[str] | None = None,
) -> str:
    """构造标量过滤表达式。

    tenant_id 和 kb_ids 是硬隔离，必须带上。
    dept/role 是软权限，按用户实际身份过滤。
    """
    conditions = [
        f'tenant_id == "{tenant_id}"',
        f'kb_id in {kb_ids}',
    ]

    if dept_ids:
        # JSON 数组字段用 array_contains_any 过滤
        dept_arr = [f'"{d}"' for d in dept_ids]
        conditions.append(
            f"array_contains_any(acl_dept_ids, {dept_arr})"
        )

    if role_ids:
        role_arr = [f'"{r}"' for r in role_ids]
        conditions.append(
            f"array_contains_any(acl_role_ids, {role_arr})"
        )

    return " and ".join(conditions)


def search_chunks(
    client: MilvusClient,
    query_vector: list[float],
    tenant_id: str,
    kb_ids: list[str],
    dept_ids: list[str] | None = None,
    role_ids: list[str] | None = None,
    top_k: int = 10,
) -> list[dict[str, Any]]:
    """向量检索 + 权限过滤，返回命中的 chunk 列表。"""

    filter_expr = build_acl_filter(
        tenant_id=tenant_id,
        kb_ids=kb_ids,
        dept_ids=dept_ids,
        role_ids=role_ids,
    )

    results = client.search(
        collection_name=COLLECTION_NAME,
        data=[query_vector],
        anns_field="vector",
        search_params={
            "metric_type": "COSINE",
            "params": {},
        },
        limit=top_k,
        filter=filter_expr,
        output_fields=[
            "chunk_id",
            "doc_id",
            "kb_id",
            "content",
            "chunk_index",
            "page_start",
            "page_end",
            "section_title",
            "file_name",
        ],
    )

    hits = []
    for hit in results[0]:
        entity = hit.entity
        hits.append({
            "chunk_id": entity.get("chunk_id"),
            "doc_id": entity.get("doc_id"),
            "kb_id": entity.get("kb_id"),
            "content": entity.get("content"),
            "chunk_index": entity.get("chunk_index"),
            "page_start": entity.get("page_start"),
            "page_end": entity.get("page_end"),
            "section_title": entity.get("section_title"),
            "file_name": entity.get("file_name"),
            "score": hit.score,
        })

    return hits


def hybrid_search_chunks(
    client: MilvusClient,
    query_vector: list[float],
    query_text: str,
    tenant_id: str,
    kb_ids: list[str],
    top_k: int = 10,
) -> list[dict[str, Any]]:
    """向量检索 + 标量过滤的混合检索示例。"""

    filter_expr = build_acl_filter(tenant_id=tenant_id, kb_ids=kb_ids)

    # 向量检索请求
    vector_req = AnnSearchRequest(
        data=[query_vector],
        anns_field="vector",
        param={"metric_type": "COSINE"},
        limit=top_k,
        filter=filter_expr,
    )

    # 如果有 BM25 稀疏向量字段，可以再加一个请求
    # sparse_req = AnnSearchRequest(...)

    results = client.hybrid_search(
        collection_name=COLLECTION_NAME,
        reqs=[vector_req],
        ranker=None,  # 单路检索时 ranker 可为 None
        limit=top_k,
        output_fields=[
            "chunk_id", "doc_id", "content",
            "page_start", "page_end", "file_name",
        ],
    )

    return [
        {
            "chunk_id": hit.entity.get("chunk_id"),
            "doc_id": hit.entity.get("doc_id"),
            "content": hit.entity.get("content"),
            "score": hit.score,
        }
        for hit in results[0]
    ]