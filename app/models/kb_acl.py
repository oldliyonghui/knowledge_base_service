import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.types import GUID, EnumStr

class AclSubjectType(str, enum.Enum):
    USER = "user"
    DEPT = "dept"
    ROLE = "role"


class AclPermission(str, enum.Enum):
    READ = "read"
    WRITE = "write"
    ADMIN = "admin"


# 权限等级，数字越大权限越高；校验时用 >= 比较
PERMISSION_LEVEL = {
    AclPermission.READ: 1,
    AclPermission.WRITE: 2,
    AclPermission.ADMIN: 3,
}


class KBAcl(Base, TimestampMixin):
    """知识库 ACL：一个主体（user/dept/role）对某知识库的权限。"""

    __tablename__ = "kb_acl"

    id: Mapped[uuid.UUID] = mapped_column(
       GUID(), primary_key=True, default=uuid.uuid4
    )
    kb_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), nullable=False, index=True
    )

    subject_type: Mapped[AclSubjectType] = mapped_column(
        EnumStr(AclSubjectType, length=32),
        nullable=False,
        index=True,
    )
    # 不设 FK：user / dept / role 三类主体共用一列
    subject_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), nullable=False, index=True
    )

    permission: Mapped[AclPermission] = mapped_column(
        EnumStr(AclPermission, length=32),
        nullable=False,
        default=AclPermission.READ,
    )

    granted_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    knowledge_base = relationship("KnowledgeBase", back_populates="acls")

    __table_args__ = (
        UniqueConstraint(
            "kb_id", "subject_type", "subject_id",
            name="uq_kb_acl_subject",
        ),
        Index(
            "ix_kb_acl_subject_lookup",
            "subject_type", "subject_id",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<KBAcl kb={self.kb_id} "
            f"{self.subject_type}={self.subject_id} {self.permission}>"
        )