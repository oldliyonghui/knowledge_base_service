import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import (
    ChatMessage,
    ChatSession,
    MessageRole,
    MessageStatus,
)
from app.models.user import User
from app.schemas.chat import (
    ChatMessageResponse,
    ChatSessionCreate,
    ChatSessionListResponse,
    ChatSessionResponse,
    ChatSessionUpdate,
)


async def create_session(
    db: AsyncSession, user: User, payload: ChatSessionCreate
) -> ChatSession:
    session = ChatSession(
        user_id=user.id,
        tenant_id=user.tenant_id,
        title=payload.title or "新会话",
        kb_ids=[str(k) for k in payload.kb_ids],
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def get_session_or_404(
    db: AsyncSession, user: User, session_id: uuid.UUID
) -> ChatSession:
    session = await db.get(ChatSession, session_id)
    if not session or session.is_deleted or session.user_id != user.id:
        # 越权一律 404，避免探测
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在"
        )
    return session


async def list_sessions(
    db: AsyncSession, user: User, page: int, page_size: int
) -> ChatSessionListResponse:
    base = select(ChatSession).where(
        ChatSession.user_id == user.id,
        ChatSession.is_deleted.is_(False),
    )
    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()

    rows = (
        await db.execute(
            base.order_by(
                func.coalesce(
                    ChatSession.last_message_at, ChatSession.created_at
                ).desc()
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    return ChatSessionListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[ChatSessionResponse.model_validate(s) for s in rows],
    )

async def update_session(
    db: AsyncSession, session: ChatSession, payload: ChatSessionUpdate
) -> ChatSession:
    data = payload.model_dump(exclude_unset=True)
    if "kb_ids" in data and data["kb_ids"] is not None:
        session.kb_ids = [str(k) for k in data.pop("kb_ids")]
    for field, value in data.items():
        if value is not None:
            setattr(session, field, value)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def delete_session(db: AsyncSession, session: ChatSession) -> None:
    session.is_deleted = True
    db.add(session)
    await db.commit()


async def list_messages(
    db: AsyncSession,
    session: ChatSession,
    page: int,
    page_size: int,
) -> tuple[int, list[ChatMessage]]:
    base = select(ChatMessage).where(ChatMessage.session_id == session.id)
    total = (
        await db.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()
    rows = (
        await db.execute(
            base.order_by(ChatMessage.created_at.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return total, list(rows)


async def load_recent_history(
    db: AsyncSession, session_id: uuid.UUID, limit: int = 12
) -> list[ChatMessage]:
    stmt = (
        select(ChatMessage)
        .where(
            ChatMessage.session_id == session_id,
            ChatMessage.status == MessageStatus.COMPLETED,
        )
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    rows.reverse()
    return rows


async def append_user_message(
    db: AsyncSession,
    session: ChatSession,
    user: User,
    question: str,
    kb_ids: list[uuid.UUID],
) -> ChatMessage:
    msg = ChatMessage(
        session_id=session.id,
        user_id=user.id,
        role=MessageRole.USER,
        content=question,
        kb_ids=[str(k) for k in kb_ids],
        status=MessageStatus.COMPLETED,
    )
    db.add(msg)
    session.message_count += 1
    session.last_message_at = datetime.now(timezone.utc)
    # 首条消息自动生成标题
    if session.title == "新会话":
        session.title = question[:50]
    db.add(session)
    await db.commit()
    await db.refresh(msg)
    return msg


async def append_assistant_message(
    db: AsyncSession,
    session: ChatSession,
    content: str,
    citations: list[dict],
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    model: str,
    status_: MessageStatus = MessageStatus.COMPLETED,
    error_msg: str | None = None,
) -> ChatMessage:
    msg = ChatMessage(
        session_id=session.id,
        role=MessageRole.ASSISTANT,
        content=content,
        citations=citations,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        model=model,
        status=status_,
        error_msg=error_msg,
    )
    db.add(msg)
    session.message_count += 1
    session.last_message_at = datetime.now(timezone.utc)
    db.add(session)
    await db.commit()
    await db.refresh(msg)
    return msg


async def set_feedback(
    db: AsyncSession,
    message_id: uuid.UUID,
    user: User,
    feedback: str,
    comment: str | None,
) -> ChatMessage:
    msg = await db.get(ChatMessage, message_id)
    if not msg or msg.role != MessageRole.ASSISTANT:
        raise HTTPException(status_code=404, detail="消息不存在")
    session = await db.get(ChatSession, msg.session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="消息不存在")
    msg.feedback = feedback
    msg.feedback_comment = comment
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    return msg