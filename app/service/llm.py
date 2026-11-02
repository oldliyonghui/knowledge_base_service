from collections.abc import AsyncIterator
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
        api_key=settings.dashscope_api_key,
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

def _sampling_kwargs(temperature: float, max_tokens: int | None) -> dict:
    """组装要合并进 DashScope 请求的采样参数。

    ChatTongyi 会把 invoke/stream 的额外 kwargs 合并进请求参数
    （_invocation_params 里的 {**self._default_params, **kwargs}），
    不显式传就只会用服务端默认值。
    """
    kwargs: dict = {"temperature": temperature}
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    return kwargs


def chat_completion(
    messages: list[dict],
    temperature: float = 0.2,
    max_tokens: int | None = None,
) -> ChatResult:
    model = _get_model()
    lc_messages = _to_lc_messages(messages)
    resp = model.invoke(lc_messages, **_sampling_kwargs(temperature, max_tokens))
    content = resp.content if isinstance(resp.content, str) else str(resp.content)
    pt, ct, tt = _extract_usage(resp)
    return ChatResult(
        content=content,
        prompt_tokens=pt,
        completion_tokens=ct,
        total_tokens=tt,
        model=settings.llm_model,
    )


async def achat_completion(
    messages: list[dict],
    temperature: float = 0.2,
    max_tokens: int | None = None,
) -> ChatResult:
    model = _get_model()
    lc_messages = _to_lc_messages(messages)
    resp = await model.ainvoke(lc_messages, **_sampling_kwargs(temperature, max_tokens))
    content = resp.content if isinstance(resp.content, str) else str(resp.content)
    pt, ct, tt = _extract_usage(resp)
    return ChatResult(
        content=content,
        prompt_tokens=pt,
        completion_tokens=ct,
        total_tokens=tt,
        model=settings.llm_model,
    )


async def achat_completion_stream(
    messages: list[dict],
    temperature: float = 0.2,
    max_tokens: int | None = None,
) -> AsyncIterator[str]:
    model = _get_model()
    lc_messages = _to_lc_messages(messages)
    async for chunk in model.astream(lc_messages, **_sampling_kwargs(temperature, max_tokens)):
        text = chunk.content
        if isinstance(text, str) and text:
            yield text
        elif isinstance(text, list):
            for piece in text:
                if isinstance(piece, dict) and piece.get("type") == "text":
                    yield piece.get("text", "")