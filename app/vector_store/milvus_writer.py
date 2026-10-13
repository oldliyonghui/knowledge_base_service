import uuid
from typing import Any

from pymilvus import MilvusClient

from app.vector_store.milvus_schema import COLLECTION_NAME


def build_milvus_record(
    chunk_id: uuid.UUID,
    embedding: list[float],
    content: str,
    doc_id: uuid.UUID,
    kb_id: uuid.UUID,
    tenant_id: uuid.UUID,
    chunk_index: int,
    page_start: int | None,
    page_end: int | None,
    section_title: str | None,
    file_name: str,
    version: int,
    embedding_model: str,
    acl_dept_ids: list[str] | None = None,
    acl_role_ids: list[str] | None = None,
) -> dict[str, Any]:
    """把关系库的 chunk 数据组装成 Milvus 可写入的记录。"""
    return {
        "chunk_id": str(chunk_id),
        "vector": embedding,
        "content": content,
        "doc_id": str(doc_id),
        "kb_id": str(kb_id),
        "tenant_id": str(tenant_id),
        "chunk_index": chunk_index,
        "page_start": page_start or 0,
        "page_end": page_end or 0,
        "section_title": section_title or "",
        "file_name": file_name,
        "version": version,
        "embedding_model": embedding_model,
        "acl_dept_ids": acl_dept_ids or [],
        "acl_role_ids": acl_role_ids or [],
    }


def upsert_chunks(
    client: MilvusClient,
    records: list[dict[str, Any]],
) -> None:
    """批量 upsert 向量。

    用 upsert 而非 insert，保证 Worker 重试时幂等：
    chunk_id 相同则覆盖，不会产生重复向量。
    """
    if not records:
        return

    # 分批写入，避免单次请求过大
    BATCH_SIZE = 256
    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i : i + BATCH_SIZE]
        client.upsert(
            collection_name=COLLECTION_NAME,
            data=batch,
        )


def delete_chunks_by_doc_id(
    client: MilvusClient,
    doc_id: uuid.UUID,
) -> int:
    """按 doc_id 批量删除该文档的所有 chunk 向量。

    使用 delete-by-filter，而不是逐条按主键删，
    避免遗漏和大量 RPC 调用。
    """
    result = client.delete(
        collection_name=COLLECTION_NAME,
        filter=f'doc_id == "{doc_id}"',
    )
    return result.get("delete_cnt", 0)

def delete_chunks_by_doc_ids(
    client: MilvusClient,
    doc_ids: list[uuid.UUID],
) -> int:
    """批量删除多个文档的向量。"""
    ids_str = ", ".join(f'"{d}"' for d in doc_ids)
    result = client.delete(
        collection_name=COLLECTION_NAME,
        filter=f"doc_id in [{ids_str}]",
    )
    return result.get("delete_cnt", 0)