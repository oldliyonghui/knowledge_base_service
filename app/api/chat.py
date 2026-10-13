import json
import uuid
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.models.chat import MessageStatus
from app.models.user import User
from app.schemas.chat import (
    AskRequest,
    AskResponse,
    ChatHistoryResponse,
    ChatMessageResponse,
    ChatSessionCreate,
    ChatSessionListResponse,
    ChatSessionResponse,
    ChatSessionUpdate,
    MessageFeedbackRequest,
)
from app.schemas.document_chunk import ChunkCitation
from app.service import chat_service, rag_service
from app.service.retrieval import to_citations
from app.service.rag_service import normalize_citations_in_answer

router = APIRouter(prefix="/chat", tags=["chat"])


# ---------- 会话 ----------
@router.post(
    "/sessions",
    response_model=ChatSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_session(
    payload: ChatSessionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatSessionResponse:
    session = await chat_service.create_session(db, current_user, payload)
    return ChatSessionResponse.model_validate(session)


@router.get("/sessions", response_model=ChatSessionListResponse)
async def list_sessions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatSessionListResponse:
    return await chat_service.list_sessions(db, current_user, page, page_size)


@router.get("/sessions/{session_id}", response_model=ChatSessionResponse)
async def get_session(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatSessionResponse:
    session = await chat_service.get_session_or_404(db, current_user, session_id)
    return ChatSessionResponse.model_validate(session)


@router.patch("/sessions/{session_id}", response_model=ChatSessionResponse)
async def update_session(
    session_id: uuid.UUID,
    payload: ChatSessionUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatSessionResponse:
    session = await chat_service.get_session_or_404(db, current_user, session_id)
    session = await chat_service.update_session(db, session, payload)
    return ChatSessionResponse.model_validate(session)


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_session(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    session = await chat_service.get_session_or_404(db, current_user, session_id)
    await chat_service.delete_session(db, session)


@router.get(
    "/sessions/{session_id}/messages",
    response_model=ChatHistoryResponse,
)
async def list_messages(
    session_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatHistoryResponse:
    session = await chat_service.get_session_or_404(db, current_user, session_id)
    total, rows = await chat_service.list_messages(db, session, page, page_size)
    return ChatHistoryResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[ChatMessageResponse.model_validate(m) for m in rows],
    )


# ---------- 问答（非流式） ----------
@router.post(
    "/sessions/{session_id}/messages",
    response_model=AskResponse,
)
async def ask(
    session_id: uuid.UUID,
    payload: AskRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AskResponse:
    session = await chat_service.get_session_or_404(db, current_user, session_id)

    kb_ids = payload.kb_ids or [uuid.UUID(k) for k in session.kb_ids]

    history = await chat_service.load_recent_history(db, session_id, limit=12)
    messages, chunks = await rag_service.prepare_rag(
        db=db,
        user=current_user,
        session=session,
        question=payload.question,
        kb_ids=kb_ids,
        top_k=payload.top_k,
        history=history,
    )

    # 1. 保存用户消息
    user_msg = await chat_service.append_user_message(
        db, session, current_user, payload.question, kb_ids
    )

    # 4. 调 LLM
    try:
        result = rag_service.run_rag_once(messages, payload.temperature)
    except Exception as e:
        assistant_msg = await chat_service.append_assistant_message(
            db, session,
            content="",
            citations=[],
            prompt_tokens=0, completion_tokens=0, total_tokens=0,
            model="",
            status_=MessageStatus.FAILED,
            error_msg=str(e),
        )
        return AskResponse(
            user_message=ChatMessageResponse.model_validate(user_msg),
            assistant_message=ChatMessageResponse.model_validate(assistant_msg),
            citations=[],
        )

    # 5. 存助手消息 + citations
    citations = to_citations(chunks)
    # 后处理：规范化回答里的 [N]
    cleaned_answer = normalize_citations_in_answer(result.content, len(citations))
    assistant_msg = await chat_service.append_assistant_message(
        db, session,
        content=cleaned_answer,
        citations=[c.model_dump(mode="json") for c in citations],
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        total_tokens=result.total_tokens,
        model=result.model,
    )

    return AskResponse(
        user_message=ChatMessageResponse.model_validate(user_msg),
        assistant_message=ChatMessageResponse.model_validate(assistant_msg),
        citations=citations,
    )


# ---------- 问答（SSE 流式） ----------

@router.post("/sessions/{session_id}/messages/stream")
async def ask_stream(
        session_id: uuid.UUID,
        payload: AskRequest,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    session = await chat_service.get_session_or_404(db, current_user, session_id)
    kb_ids = payload.kb_ids or [uuid.UUID(k) for k in session.kb_ids]

    # ---------- 1. 先加载历史 ----------
    history = await chat_service.load_recent_history(db, session_id, limit=12)

    # ---------- 2. 先检索（失败就抛，不落 user 消息） ----------
    messages, chunks = await rag_service.prepare_rag(
        db=db,
        user=current_user,
        session=session,
        question=payload.question,
        kb_ids=kb_ids,
        top_k=payload.top_k,
        history=history,
    )

    # ---------- 3. 检索成功后才落 user 消息 ----------
    user_msg = await chat_service.append_user_message(
        db, session, current_user, payload.question, kb_ids
    )

    async def event_stream() -> AsyncGenerator[bytes, None]:
        citations = to_citations(chunks)
        yield _sse("citations", {
            "user_message_id": str(user_msg.id),
            "items": [c.model_dump(mode="json") for c in citations],
        })

        full = []
        try:
            for delta in rag_service.run_rag_stream(messages, payload.temperature):
                full.append(delta)
                yield _sse("delta", {"text": delta})
        except Exception as e:
            yield _sse("error", {"message": str(e)})
            # 失败也落库
            raw = "".join(full)
            cleaned = normalize_citations_in_answer(raw, len(citations))
            await chat_service.append_assistant_message(
                db, session,
                content=cleaned,
                citations=[c.model_dump(mode="json") for c in citations],
                prompt_tokens=0, completion_tokens=0, total_tokens=0,
                model="",
                status_=MessageStatus.FAILED,
                error_msg=str(e),
            )
            return
        raw = "".join(full)
        cleaned = normalize_citations_in_answer(raw, len(citations))
        assistant_msg = await chat_service.append_assistant_message(
            db, session,
            content=cleaned,
            citations=[c.model_dump(mode="json") for c in citations],
            prompt_tokens=0, completion_tokens=0, total_tokens=0,
            model="",
        )
        yield _sse("done", {
            "assistant_message_id": str(assistant_msg.id),
            "citations": [c.model_dump(mode="json") for c in citations],
        })
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")


# ---------- 反馈 ----------
@router.post(
    "/messages/{message_id}/feedback",
    response_model=ChatMessageResponse,
)
async def message_feedback(
    message_id: uuid.UUID,
    payload: MessageFeedbackRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatMessageResponse:
    msg = await chat_service.set_feedback(
        db, message_id, current_user, payload.feedback, payload.comment
    )
    return ChatMessageResponse.model_validate(msg)