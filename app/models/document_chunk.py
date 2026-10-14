import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.types import GUID, EnumStr, UtcDateTime
from app.models.base import Base, TimestampMixin


class VectorStatus(str, enum.Enum):
    """分块向量在向量库中的状态。"""

    PENDING = "pending"      # 已入库关系库，尚未写向量
    INDEXED = "indexed"      # 已成功写入向量库
    FAILED = "failed"        # 写入失败
    DELETED = "deleted"      # 已从向量库删除


class DocumentChunk(Base, TimestampMixin):
    """文档分块表。

    存分块原文、页码、token 数等；向量和过滤元数据放向量库，
    向量库记录的 id == 本表 chunk_id。
    """

    __tablename__ = "document_chunks"

    # 主键：chunk_id，与向量库记录 id 完全一致
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        primary_key=True,
        default=uuid.uuid4,
    )

    # 归属：文档 + 知识库 + 租户（冗余 kb/tenant 便于检索过滤）
    doc_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kb_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        nullable=False,
        index=True,
    )

    # 分块序号：同一文档内从 0 递增
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)

    # 分块内容
    content: Mapped[str] = mapped_column(
        Text, nullable=False, comment="分块原文，用于引用、高亮、重排"
    )
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 定位信息
    page_start: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    page_end: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    section_title: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True, comment="章节标题，便于展示"
    )

    # 向量化信息
    vector_status: Mapped[VectorStatus] = mapped_column(
        EnumStr(VectorStatus, length=32),
        nullable=False,
        default=VectorStatus.PENDING,
        index=True,
    )
    embedding_model: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True
    )
    vector_dim: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    vector_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 其他解析元数据，JSON 字符串，避免过早建列
    metadata_json: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="额外元数据，如 bbox、表格标记等"
    )

    # 软删
    is_deleted: Mapped[bool] = mapped_column(
        default=False, nullable=False, index=True
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        UtcDateTime, nullable=True
    )

    # 关系
    document = relationship("Document", back_populates="chunks", lazy="selectin")

    __table_args__ = (
        UniqueConstraint(
            "doc_id", "chunk_index", name="uq_chunks_doc_index"
        ),
        Index("ix_chunks_kb_vector_status", "kb_id", "vector_status"),
        Index("ix_chunks_doc_index", "doc_id", "chunk_index"),
    )

    def __repr__(self) -> str:
        return (
            f"<DocumentChunk chunk_id={self.chunk_id} "
            f"doc_id={self.doc_id} idx={self.chunk_index}>"
        )
