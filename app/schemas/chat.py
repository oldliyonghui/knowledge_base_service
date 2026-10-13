import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.chat import MessageRole, MessageStatus
from app.schemas.document_chunk import ChunkCitation


# ---------- 会话 ----------
class ChatSessionCreate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=255)
    kb_ids: list[uuid.UUID] = Field(
        ...,
        min_length=1,
        description="本次会话默认检索的知识库范围",
    )


class ChatSessionUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=255)
    kb_ids: Optional[list[uuid.UUID]] = None


class ChatSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    title: str
    kb_ids: list[uuid.UUID]
    message_count: int
    last_message_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class ChatSessionListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[ChatSessionResponse]


# ---------- 消息 ----------
class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    kb_ids: Optional[list[uuid.UUID]] = Field(
        default=None,
        description="覆盖会话默认范围；为空则用会话默认 kb_ids",
    )
    top_k: int = Field(default=8, ge=1, le=30)
    stream: bool = False
    temperature: float = Field(default=0.2, ge=0, le=2)


class ChatMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_id: uuid.UUID
    role: MessageRole
    content: str
    citations: Optional[list[dict]] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    model: Optional[str] = None
    status: MessageStatus
    error_msg: Optional[str] = None
    feedback: Optional[str] = None
    created_at: datetime


class AskResponse(BaseModel):
    """一次问答的完整返回。"""

    user_message: ChatMessageResponse
    assistant_message: ChatMessageResponse
    citations: list[ChunkCitation] = Field(default_factory=list)


class ChatHistoryResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[ChatMessageResponse]


# ---------- 反馈 ----------
class MessageFeedbackRequest(BaseModel):
    feedback: str = Field(..., pattern="^(up|down)$")
    comment: Optional[str] = Field(default=None, max_length=1000)