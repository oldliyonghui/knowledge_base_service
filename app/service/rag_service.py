import uuid
from collections.abc import Iterator
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.chat import ChatMessage, MessageRole, MessageStatus, ChatSession
from app.service import llm, retrieval
from app.service.permission import list_readable_kb_ids
from app.service.retrieval import RetrievedChunk
import re

_CITE_PATTERN = re.compile(r"\[(\d+)\]")

SYSTEM_PROMPT = """你是一个企业知识库助手。请严格依据下面提供的"检索上下文"回答用户问题。

要求：
1. 只使用检索上下文中的信息作答，不要编造事实。
2. 如果上下文不足以回答，明确说明"根据现有资料无法回答"，不要臆测。
3. 回答使用简体中文，条理清晰，必要时使用要点。
4. 引用时用 [1]、[2] 这样的序号，与上下文编号对应。
"""


@dataclass
class RagResult:
    answer: str
    citations: list[RetrievedChunk]
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    model: str


def _build_context(chunks: list[RetrievedChunk]) -> str:
    """把检索结果拼成编号上下文块。"""
    if not chunks:
        return "（无相关检索结果）"

    parts: list[str] = []
    total_tokens = 0
    max_tokens = settings.rag_max_context_tokens

    for i, c in enumerate(chunks, start=1):
        source = c.file_name or ""
        page = (
            f"p.{c.page_start}" if c.page_start == c.page_end
            else f"p.{c.page_start}-{c.page_end}"
        )
        header = f"[{i}] 来源：{source} {page}".strip()
        block = f"{header}\n{c.content}"

        # 简单按字符估算 token，够用；精细可换 tiktoken
        approx_tokens = len(block) // 2
        if total_tokens + approx_tokens > max_tokens:
            break
        parts.append(block)
        total_tokens += approx_tokens

    return "\n\n---\n\n".join(parts)


def _build_messages(
    question: str,
    chunks: list[RetrievedChunk],
    history: list[ChatMessage],
    history_turns: int = 6,
) -> list[dict]:
    context = _build_context(chunks)
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "system",
            "content": f"检索上下文如下：\n\n{context}",
        },
    ]
    # 最近若干轮历史，帮助指代消解
    for msg in history[-history_turns:]:
        if msg.role in (MessageRole.USER, MessageRole.ASSISTANT):
            messages.append({
                "role": msg.role.value,
                "content": msg.content,
            })
    messages.append({"role": "user", "content": question})
    return messages


async def prepare_rag(
    db: AsyncSession,
    user,
    session: ChatSession,
    question: str,
    kb_ids: list[uuid.UUID],
    top_k: int,
    history: list[ChatMessage],
) -> tuple[list[dict], list[RetrievedChunk]]:
    """检索 + 组装 messages。返回 (messages, chunks)。"""

    # 1. 权限：把用户请求的 kb_ids 与可读 kb 取交集
    readable = set(
        await list_readable_kb_ids(db, user, user.tenant_id)
    )
    allowed_kb_ids = [k for k in kb_ids if k in readable]
    if not allowed_kb_ids:
        return _build_messages(question, [], history), []

    # 2. 检索
    chunks = await retrieval.retrieve(
        db=db,
        user=user,
        readable_kb_ids=allowed_kb_ids,
        question=question,
        top_k=top_k,
    )

    # 3. 组装 prompt
    messages = _build_messages(question, chunks, history)
    return messages, chunks


def run_rag_once(
    messages: list[dict],
    temperature: float,
) -> llm.ChatResult:
    return llm.chat_completion(messages, temperature=temperature)


def run_rag_stream(
    messages: list[dict],
    temperature: float,
) -> Iterator[str]:
    return llm.chat_completion_stream(messages, temperature=temperature)


def normalize_citations_in_answer(answer: str, n_citations: int) -> str:
    """规范化 LLM 回答里的引用编号。

    规则：
    1. 没有 citations 时，把回答里所有 [N] 都删掉
    2. 编号越界的（0 或 > n），钳制到 [1, n] 范围
    3. 其他保持原样

    这样保证前端拿到的 [N] 一定能对应上 citations[N-1]。
    """
    if n_citations == 0:
        # 没有引用来源，把回答里的编号全删掉，避免误导
        return _CITE_PATTERN.sub("", answer)

    def _clamp(m: re.Match) -> str:
        idx = int(m.group(1))
        idx = max(1, min(idx, n_citations))
        return f"[{idx}]"

    return _CITE_PATTERN.sub(_clamp, answer)