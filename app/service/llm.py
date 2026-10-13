from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache

from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.core.config import settings


@dataclass
class ChatResult:
    content: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    model: str


@lru_cache
def _get_model() -> ChatTongyi:
    return ChatTongyi(
        model=settings.llm_model,
    )


def _to_lc_messages(messages: list[dict]) -> list:
    out = []
    for m in messages:
        role, content = m.get("role"), m.get("content", "")
        if role == "system":
            out.append(SystemMessage(content=content))
        elif role == "assistant":
            out.append(AIMessage(content=content))
        else:
            out.append(HumanMessage(content=content))
    return out


def _extract_usage(resp) -> tuple[int, int, int]:
    meta = getattr(resp, "response_metadata", {}) or {}
    usage = meta.get("token_usage") or {}
    return (
        usage.get("input_tokens", 0),
        usage.get("output_tokens", 0),
        usage.get("total_tokens", 0),
    )


def chat_completion(
    messages: list[dict],
    temperature: float = 0.2,
    max_tokens: int | None = None,
) -> ChatResult:
    model = _get_model()
    lc_messages = _to_lc_messages(messages)
    resp = model.invoke(lc_messages)
    content = resp.content if isinstance(resp.content, str) else str(resp.content)
    pt, ct, tt = _extract_usage(resp)
    return ChatResult(
        content=content,
        prompt_tokens=pt,
        completion_tokens=ct,
        total_tokens=tt,
        model=settings.llm_model,
    )


def chat_completion_stream(
    messages: list[dict],
    temperature: float = 0.2,
    max_tokens: int | None = None,
) -> Iterator[str]:
    model = _get_model()
    lc_messages = _to_lc_messages(messages)
    for chunk in model.stream(lc_messages):
        text = chunk.content
        if isinstance(text, str) and text:
            yield text
        elif isinstance(text, list):
            for piece in text:
                if isinstance(piece, dict) and piece.get("type") == "text":
                    yield piece.get("text", "")