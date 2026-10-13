import uuid
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF

from app.worker.exceptions import UnrecoverableIngestError


@dataclass
class ParsedPage:
    page_number: int  # 从 1 开始
    text: str


@dataclass
class ParsedDocument:
    page_count: int
    pages: list[ParsedPage]


def parse_pdf(file_path: Path) -> ParsedDocument:
    """解析本地 PDF 文件，逐页提取文本。

    - 文本型 PDF：直接取 text
    - 图片型 PDF：如果页面文本为空，后续可接 OCR（暂不实现）
    """
    if not file_path.exists():
        raise UnrecoverableIngestError(f"PDF 文件不存在: {file_path}")

    try:
        doc = fitz.open(str(file_path))
    except Exception as e:
        raise UnrecoverableIngestError(f"PDF 打开失败: {e}") from e

    try:
        if doc.is_encrypted and not doc.authenticate(""):
            raise UnrecoverableIngestError("PDF 已加密，无法解析")

        pages: list[ParsedPage] = []
        for idx in range(doc.page_count):
            page = doc.load_page(idx)
            text = page.get_text("text") or ""
            text = _normalize_text(text)
            pages.append(ParsedPage(page_number=idx + 1, text=text))

        return ParsedDocument(page_count=doc.page_count, pages=pages)
    finally:
        doc.close()


def _normalize_text(text: str) -> str:
    """去掉多余空行和不可见字符，保留基本段落结构。"""
    if not text:
        return ""
    lines = [ln.strip() for ln in text.splitlines()]
    # 去掉连续空行，压成一个空行
    out: list[str] = []
    prev_empty = False
    for ln in lines:
        if not ln:
            if not prev_empty:
                out.append("")
            prev_empty = True
        else:
            out.append(ln)
            prev_empty = False
    return "\n".join(out).strip()