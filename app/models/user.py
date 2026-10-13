import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Table,
    UniqueConstraint,
)

from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.types import GUID


# 用户-角色 多对多
user_roles = Table(
    "user_roles",
    Base.metadata,
    Column(
        "user_id",
        GUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "role_id",
        GUID(),
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Role(Base, TimestampMixin):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)

    def __repr__(self) -> str:
        return f"<Role code={self.code}>"


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )

    # 租户 / 部门
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), nullable=False, index=True
    )
    dept_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID(), nullable=True, index=True
    )

    # 账号
    username: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    email: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, unique=True, index=True
    )
    full_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # 密码
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)

    # 状态
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, index=True
    )
    is_superuser: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # 关系
    roles: Mapped[list[Role]] = relationship(
        "Role",
        secondary=user_roles,
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_users_tenant_dept", "tenant_id", "dept_id"),
        UniqueConstraint("tenant_id", "username", name="uq_users_tenant_username"),
    )

    @property
    def role_ids(self) -> list[uuid.UUID]:
        return [r.id for r in self.roles]

    @property
    def role_codes(self) -> list[str]:
        return [r.code for r in self.roles]

    def __repr__(self) -> str:
        return f"<User username={self.username}>"