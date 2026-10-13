from dataclasses import dataclass

import tiktoken

from app.core.config import settings
from app.worker.pipeline.pdf_parser import ParsedPage
import re

_ENCODER = tiktoken.get_encoding("cl100k_base")

FAQ_PATTERN = re.compile(
    r"(\d+)\.\s*\*\*(.+?)\*\*\s*\n?\s*[-–]\s*(.+?)"
    r"(?=\n\d+\.\s*\*\*|\n#{1,6}\s|\n---|\Z)",   # 加 \n#{1,6}\s|\n---
    re.DOTALL,
)


@dataclass
class Chunk:
    chunk_index: int
    content: str
    token_count: int
    page_start: int
    page_end: int
    section_title: str | None = None


def count_tokens(text: str) -> int:
    return len(_ENCODER.encode(text, disallowed_special=()))

def chunk_faq_pages(pages: list[ParsedPage]) -> list[Chunk]:
    """FAQ 专用分块：每条问答 = 一个 chunk。"""
    chunks = []
    idx = 0
    for page in pages:
        for m in FAQ_PATTERN.finditer(page.text):
            num, question, answer = m.group(1), m.group(2).strip(), m.group(3).strip()
            content = f"问：{question}\n答：{answer}"
            if len(content) < 20:
                continue
            chunks.append(Chunk(
                chunk_index=idx,
                content=content,
                token_count=len(content) // 2,
                page_start=page.page_number,
                page_end=page.page_number,
                section_title=None,
            ))
            idx += 1
    return chunks

def _chunk_by_tokens(pages: list[ParsedPage]) -> list[Chunk]:
    """逐页分块：每页按 chunk_size 切分，页内带 overlap。

    策略简单、页码定位准确；后续要做跨页合并可在此扩展。
    """
    chunks: list[Chunk] = []
    idx = 0
    for page in pages:
        text = page.text
        if not text or len(text) < settings.chunk_min_chars:
            continue

        pieces = _split_by_tokens(
            text,
            chunk_size=settings.chunk_size,
            overlap=settings.chunk_overlap,
        )
        for piece in pieces:
            if len(piece) < settings.chunk_min_chars:
                continue
            chunks.append(
                Chunk(
                    chunk_index=idx,
                    content=piece,
                    token_count=count_tokens(piece),
                    page_start=page.page_number,
                    page_end=page.page_number,
                )
            )
            idx += 1

    return chunks

def chunk_pages(pages):
    """自动选择分块策略：FAQ 模式匹配多就用 FAQ 分块，否则走通用。"""
    total_text = "\n".join(p.text for p in pages)
    faq_hits = len(FAQ_PATTERN.findall(total_text))
    if faq_hits >= 5:  # 至少 5 条问答，判定为 FAQ 文档
        return chunk_faq_pages(pages)
    return _chunk_by_tokens(pages)  # 你原来的通用分块


def _split_by_tokens(text: str, chunk_size: int, overlap: int) -> list[str]:
    """按 token 切分，相邻块之间保留 overlap 个 token 的上下文。"""
    tokens = _ENCODER.encode(text, disallowed_special=())
    if len(tokens) <= chunk_size:
        return [text]

    step = max(1, chunk_size - overlap)
    pieces: list[str] = []
    for start in range(0, len(tokens), step):
        end = min(start + chunk_size, len(tokens))
        pieces.append(_ENCODER.decode(tokens[start:end]))
        if end >= len(tokens):
            break
    return pieces