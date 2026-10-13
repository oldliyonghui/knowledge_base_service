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
from app.models.types import GUID, EnumStr


class KBVisibility(str, enum.Enum):
    """知识库可见性，作为 ACL 的默认兜底。"""

    PRIVATE = "private"        # 只有 owner + ACL 里明确授权的人可见
    TENANT = "tenant"          # 同租户所有人可读
    PUBLIC = "public"          # 所有人可读（企业内一般不用）


class KnowledgeBase(Base, TimestampMixin):
    __tablename__ = "knowledge_bases"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), nullable=False, index=True
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    visibility: Mapped[KBVisibility] = mapped_column(
        EnumStr(KBVisibility, length=32),
        nullable=False,
        default=KBVisibility.PRIVATE,
        index=True,
    )

    # 默认 RAG 参数，可被文档级覆盖
    embedding_model: Mapped[str] = mapped_column(
        String(128), nullable=False, default="text-embedding-3-small"
    )
    embedding_dim: Mapped[int] = mapped_column(Integer, nullable=False, default=1536)
    chunk_size: Mapped[int] = mapped_column(Integer, nullable=False, default=512)
    chunk_overlap: Mapped[int] = mapped_column(Integer, nullable=False, default=64)

    # 统计
    doc_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    # 软删
    is_deleted: Mapped[bool] = mapped_column(
        default=False, nullable=False, index=True
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        nullable=True
    )

    # 关系
    acls: Mapped[list["KBAcl"]] = relationship(
        "KBAcl",
        back_populates="knowledge_base",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_kb_tenant_name"),
        Index("ix_kb_tenant_visibility", "tenant_id", "visibility"),
    )

    def __repr__(self) -> str:
        return f"<KnowledgeBase id={self.id} name={self.name}>"