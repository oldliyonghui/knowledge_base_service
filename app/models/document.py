import enum
import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.types import GUID, EnumStr, UtcDateTime


class DocumentStatus(str, enum.Enum):
    """文档处理状态。"""

    UPLOADED = "uploaded"      # 文件已上传，等待解析
    PARSING = "parsing"        # 正在解析 PDF
    CHUNKING = "chunking"      # 正在分块
    EMBEDDING = "embedding"    # 正在向量化
    INDEXING = "indexing"      # 正在写入向量库
    INDEXED = "indexed"        # 已完成
    FAILED = "failed"          # 处理失败
    DELETED = "deleted"        # 已软删除


class Document(Base, TimestampMixin):
    """文档表。

    只存文档级元数据与状态；分块原文放 document_chunks；
    向量和过滤元数据放向量库，通过 doc_id / chunk_id 关联。
    """

    __tablename__ = "documents"

    # 主键：文档 ID，直接用 UUID，和向量库 payload 中的 doc_id 一致
    id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        primary_key=True,
        default=uuid.uuid4,
    )

    # 归属：租户 + 知识库
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        nullable=False,
        index=True,
    )
    kb_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        nullable=False,
        index=True,
    )

    # 上传者
    uploader_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        nullable=False,
        index=True,
    )

    # 文件基础信息
    file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    object_key: Mapped[str] = mapped_column(
        String(1024),
        nullable=False,
        comment="对象存储中的路径，如 MinIO/S3 key",
    )
    file_hash: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="文件内容 SHA256，用于去重和幂等",
    )
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_type: Mapped[str] = mapped_column(
        String(128), nullable=False, default="application/pdf"
    )

    # 处理状态
    status: Mapped[DocumentStatus] = mapped_column(
        EnumStr(DocumentStatus, length=32),
        nullable=False,
        default=DocumentStatus.UPLOADED,
        index=True,
    )
    page_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    chunk_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_msg: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 版本与软删
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_deleted: Mapped[bool] = mapped_column(
        default=False, nullable=False, index=True
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        UtcDateTime, nullable=True
    )

    # 使用的 embedding 模型（记录解析时用的版本，便于重建索引）
    embedding_model: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True
    )

    chunks: Mapped[list["DocumentChunk"]] = relationship(
        "DocumentChunk",
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        # 同一知识库内，同一 hash 只保留一份有效文档
        UniqueConstraint(
            "kb_id", "file_hash", "version",
            name="uq_documents_kb_hash_version",
        ),
        Index("ix_documents_kb_status", "kb_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<Document id={self.id} name={self.file_name} status={self.status}>"
