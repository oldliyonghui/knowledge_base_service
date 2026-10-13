from pymilvus import (
    MilvusClient,
    DataType,
    FieldSchema,
    CollectionSchema,
)

COLLECTION_NAME = "knowledge_chunks"
VECTOR_DIM = 386  #embedding 模型的维度


def get_milvus_client(uri: str = "http://localhost:19530", token: str = "") -> MilvusClient:
    return MilvusClient(uri=uri, token=token)


def create_collection_if_not_exists(client: MilvusClient) -> None:
    """创建 Collection，如果已存在则跳过。"""

    if client.has_collection(collection_name=COLLECTION_NAME):
        return

    fields = [
        # 主键：直接复用关系库的 chunk_id，保证两边一致
        FieldSchema(
            name="chunk_id",
            dtype=DataType.VARCHAR,
            is_primary=True,
            max_length=64,
        ),
        FieldSchema(
            name="vector",
            dtype=DataType.FLOAT_VECTOR,
            dim=VECTOR_DIM,
        ),
        # 原文副本，检索后可直接返回，减少回表
        FieldSchema(
            name="content",
            dtype=DataType.VARCHAR,
            max_length=65535,
        ),
        # 关联字段
        FieldSchema(name="doc_id", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="kb_id", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="tenant_id", dtype=DataType.VARCHAR, max_length=64),
        # 定位信息
        FieldSchema(name="chunk_index", dtype=DataType.INT64),
        FieldSchema(name="page_start", dtype=DataType.INT64),
        FieldSchema(name="page_end", dtype=DataType.INT64),
        FieldSchema(name="section_title", dtype=DataType.VARCHAR, max_length=512),
        FieldSchema(name="file_name", dtype=DataType.VARCHAR, max_length=512),
        # 版本与模型
        FieldSchema(name="version", dtype=DataType.INT64),
        FieldSchema(name="embedding_model", dtype=DataType.VARCHAR, max_length=128),
        # 权限标签：JSON 数组，用于过滤
        FieldSchema(name="acl_dept_ids", dtype=DataType.JSON),
        FieldSchema(name="acl_role_ids", dtype=DataType.JSON),
    ]

    schema = CollectionSchema(
        fields=fields,
        description="RAG knowledge chunk vectors",
        enable_dynamic_field=False,
    )

    client.create_collection(
        collection_name=COLLECTION_NAME,
        schema=schema,
    )

    # 为向量字段创建索引
    index_params = client.prepare_index_params()
    index_params.add_index(
        field_name="vector",
        index_type="AUTOINDEX",   # 生产环境可按需换 HNSW / IVF_FLAT
        metric_type="COSINE",
    )
    # 为高频过滤字段建标量索引，加速 pre-filter
    index_params.add_index(
        field_name="doc_id",
        index_type="INVERTED",
    )
    index_params.add_index(
        field_name="kb_id",
        index_type="INVERTED",
    )
    index_params.add_index(
        field_name="tenant_id",
        index_type="INVERTED",
    )

    client.create_index(
        collection_name=COLLECTION_NAME,
        index_params=index_params,
    )

    # 加载到内存
    client.load_collection(collection_name=COLLECTION_NAME)