import uuid
from typing import Any

from pymilvus import (
    CollectionSchema,
    DataType,
    FieldSchema,
    MilvusClient,
)

from app.core.config import settings
from app.core.config import settings
COLLECTION_NAME = settings.milvus_collection
_client: MilvusClient | None = None


def get_client() -> MilvusClient:
    global _client
    if _client is None:
        _client = MilvusClient(
            uri=settings.milvus_uri,
            token=settings.milvus_token or "",
        )
    return _client


def ensure_collection() -> None:
    client = get_client()
    if client.has_collection(COLLECTION_NAME):
        client.load_collection(COLLECTION_NAME)
        return

    fields = [
        FieldSchema("chunk_id", DataType.VARCHAR, is_primary=True, max_length=64),
        FieldSchema("vector", DataType.FLOAT_VECTOR, dim=settings.embedding_dim),
        FieldSchema("content", DataType.VARCHAR, max_length=65535),
        FieldSchema("doc_id", DataType.VARCHAR, max_length=64),
        FieldSchema("kb_id", DataType.VARCHAR, max_length=64),
        FieldSchema("tenant_id", DataType.VARCHAR, max_length=64),
        FieldSchema("chunk_index", DataType.INT64),
        FieldSchema("page_start", DataType.INT64),
        FieldSchema("page_end", DataType.INT64),
        FieldSchema("section_title", DataType.VARCHAR, max_length=512),
        FieldSchema("file_name", DataType.VARCHAR, max_length=512),
        FieldSchema("version", DataType.INT64),
        FieldSchema("embedding_model", DataType.VARCHAR, max_length=128),
        FieldSchema("acl_dept_ids", DataType.JSON),
        FieldSchema("acl_role_ids", DataType.JSON),
    ]
    schema = CollectionSchema(fields=fields, description="RAG chunk vectors")
    client.create_collection(collection_name=COLLECTION_NAME, schema=schema)

    index_params = client.prepare_index_params()
    index_params.add_index(
        field_name="vector", index_type="AUTOINDEX", metric_type="COSINE"
    )
    index_params.add_index(field_name="doc_id", index_type="INVERTED")
    index_params.add_index(field_name="kb_id", index_type="INVERTED")
    index_params.add_index(field_name="tenant_id", index_type="INVERTED")
    client.create_index(COLLECTION_NAME, index_params)
    client.load_collection(COLLECTION_NAME)


def build_record(
    *,
    chunk_id: uuid.UUID,
    vector: list[float],
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
    return {
        "chunk_id": str(chunk_id),
        "vector": vector,
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


def upsert_records(records: list[dict[str, Any]], batch_size: int = 256) -> None:
    if not records:
        return
    client = get_client()
    for i in range(0, len(records), batch_size):
        client.upsert(
            collection_name=COLLECTION_NAME,
            data=records[i : i + batch_size],
        )


def delete_by_doc_id(doc_id: uuid.UUID) -> int:
    client = get_client()
    res = client.delete(
        collection_name=COLLECTION_NAME,
        filter=f'doc_id == "{doc_id}"',
    )
    return res.get("delete_cnt", 0)