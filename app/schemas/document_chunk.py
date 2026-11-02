import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.document_chunk import VectorStatus


# ---------- 基础 ----------
class DocumentChunkBase(BaseModel):
    content: str
    chunk_index: int = Field(..., ge=0)
    token_count: int = Field(default=0, ge=0)
    page_start: Optional[int] = Field(default=None, ge=1)
    page_end: Optional[int] = Field(default=None, ge=1)
    section_title: Optional[str] = Field(default=None, max_length=512)


# ---------- 创建（内部使用，Worker 分块后构造） ----------
class DocumentChunkCreate(DocumentChunkBase):
    """分块写入关系库时用，客户端不直接构造。"""

    doc_id: uuid.UUID
    kb_id: uuid.UUID
    tenant_id: uuid.UUID
    embedding_model: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


# ---------- 更新 ----------
class DocumentChunkUpdate(BaseModel):
    """分块级状态更新，主要给 Worker 用。"""

    vector_status: Optional[VectorStatus] = None
    embedding_model: Optional[str] = None
    vector_dim: Optional[int] = None
    vector_error: Optional[str] = None


# ---------- 响应：完整 ----------
class DocumentChunkResponse(DocumentChunkBase):
    """分块详情，一般给检索调试、引用展示用。"""

    model_config = ConfigDict(from_attributes=True)

    chunk_id: uuid.UUID
    doc_id: uuid.UUID
    kb_id: uuid.UUID
    vector_status: VectorStatus
    embedding_model: Optional[str] = None
    vector_dim: Optional[int] = None
    created_at: datetime
    updated_at: datetime


# ---------- 响应：引用片段 ----------
class ChunkCitation(BaseModel):
    """问答回答里返回给前端的引用信息。"""

    chunk_id: uuid.UUID
    doc_id: uuid.UUID
    file_name: Optional[str] = None
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    section_title: Optional[str] = None
    content: Optional[str] = None
    score: Optional[float] = Field(
        default=None,
        description=(
            "最终相关度分：开启 rerank 时等于 rerank_score（0~1）；"
            "未开启 rerank 时为原始召回分（余弦 -1~1 或 BM25 原始分），量纲不同，不要直接跨请求比较"
        ),
    )
    rerank_score: Optional[float] = Field(
        default=None,
        description="rerank 模型给出的相关度分（0~1），未启用 rerank 或 rerank 失败时为 null",
    )


# ---------- 列表 ----------
class DocumentChunkListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[DocumentChunkResponse]


# ---------- 检索命中（内部/调试） ----------
class ChunkSearchHit(BaseModel):
    """向量库检索 + 回表后组装的命中结果。"""

    chunk_id: uuid.UUID
    doc_id: uuid.UUID
    kb_id: uuid.UUID
    chunk_index: int
    content: str
    score: float
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    section_title: Optional[str] = None
    file_name: Optional[str] = None