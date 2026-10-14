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
)
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.types import GUID, EnumStr, UtcDateTime


class MessageRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class MessageStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class ChatSession(Base, TimestampMixin):
    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), nullable=False, index=True
    )

    title: Mapped[str] = mapped_column(
        String(255), nullable=False, default="新会话"
    )

    # 该会话默认检索的知识库范围
    kb_ids: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )

    message_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    last_message_at: Mapped[Optional[datetime]] = mapped_column(
        UtcDateTime, nullable=True, index=True
    )

    is_deleted: Mapped[bool] = mapped_column(
        default=False, nullable=False, index=True
    )

    messages: Mapped[list["ChatMessage"]] = relationship(
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ChatMessage.created_at",
    )

    __table_args__ = (
        Index("ix_chat_sessions_user_last", "user_id", "last_message_at"),
    )


class ChatMessage(Base, TimestampMixin):
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    role: Mapped[MessageRole] = mapped_column(
        EnumStr(MessageRole, length=16), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # 只对 user 消息记录：本次问答使用的 kb_ids
    kb_ids: Mapped[Optional[list[str]]] = mapped_column(
        JSON, nullable=True
    )

    # 引用：chunk 列表
    citations: Mapped[Optional[list[dict]]] = mapped_column(
        JSON, nullable=True
    )

    # token 用量
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # 使用的模型
    model: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    status: Mapped[MessageStatus] = mapped_column(
        EnumStr(MessageStatus, length=32),
        nullable=False,
        default=MessageStatus.COMPLETED,
        index=True,
    )
    error_msg: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 反馈
    feedback: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True
    )  # "up" / "down"
    feedback_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    session: Mapped["ChatSession"] = relationship(
        "ChatSession", back_populates="messages"
    )

    __table_args__ = (
        Index("ix_chat_messages_session_created", "session_id", "created_at"),
    )
