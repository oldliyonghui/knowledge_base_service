import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.knowledge_base import KBVisibility
from app.schemas.kb_acl import KBAclCreate, KBAclResponse


class KnowledgeBaseBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: Optional[str] = None
    visibility: KBVisibility = KBVisibility.PRIVATE


class KnowledgeBaseCreate(KnowledgeBaseBase):
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    chunk_size: int = Field(default=512, ge=64, le=4096)
    chunk_overlap: int = Field(default=64, ge=0, le=1024)
    # 创建时顺带授予一批 ACL，可选
    acls: list[KBAclCreate] = Field(default_factory=list)


class KnowledgeBaseUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=128)
    description: Optional[str] = None
    visibility: Optional[KBVisibility] = None
    embedding_model: Optional[str] = None
    embedding_dim: Optional[int] = None
    chunk_size: Optional[int] = Field(default=None, ge=64, le=4096)
    chunk_overlap: Optional[int] = Field(default=None, ge=0, le=1024)


class KnowledgeBaseResponse(KnowledgeBaseBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    owner_id: uuid.UUID
    embedding_model: str
    embedding_dim: int
    chunk_size: int
    chunk_overlap: int
    doc_count: int
    chunk_count: int
    created_at: datetime
    updated_at: datetime


class KnowledgeBaseDetail(KnowledgeBaseResponse):
    acls: list[KBAclResponse] = Field(default_factory=list)


class KnowledgeBaseListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[KnowledgeBaseResponse]