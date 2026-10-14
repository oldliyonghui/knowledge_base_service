"""BM25 关键词索引。

内存型实现，适合中小规模（< 10 万 chunk）。

- 单进程 FastAPI 下全局共享一个索引
- 文档 indexed / deleted 时增量更新
- 支持按 tenant_id + kb_id 过滤
"""

import logging
import threading
from dataclasses import dataclass, field

import jieba
from rank_bm25 import BM25Okapi

logger = logging.getLogger(__name__)


def tokenize(text: str) -> list[str]:
    """中文分词 + 英文小写。"""
    if not text:
        return []
    # jieba 分词，去掉空白和单字符（可选）
    tokens = [t.strip().lower() for t in jieba.cut(text)]
    return [t for t in tokens if t and len(t) >= 1]


@dataclass
class BM25Doc:
    chunk_id: str
    content: str
    doc_id: str
    kb_id: str
    tenant_id: str
    page_start: int | None = None
    page_end: int | None = None
    section_title: str | None = None
    file_name: str | None = None


class BM25Index:
    """线程安全的 BM25 索引。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._docs: list[BM25Doc] = []
        self._bm25: BM25Okapi | None = None
        # 快速查找：chunk_id -> 索引位置
        self._id_to_pos: dict[str, int] = {}

    def build(self, docs: list[BM25Doc]) -> None:
        """全量重建。"""
        with self._lock:
            self._docs = list(docs)
            self._id_to_pos = {d.chunk_id: i for i, d in enumerate(docs)}
            if docs:
                tokenized = [tokenize(d.content) for d in docs]
                self._bm25 = BM25Okapi(tokenized)
            else:
                self._bm25 = None
            logger.info("BM25 索引已重建，共 %d 条", len(docs))

    def add_documents(self, docs: list[BM25Doc]) -> None:
        """增量添加（简单实现：合并后重建）。

        数据量小时重建很快；数据量大时应改为真正的增量更新。
        """
        if not docs:
            return
        with self._lock:
            existing = {d.chunk_id: d for d in self._docs}
            for d in docs:
                existing[d.chunk_id] = d
            new_docs = list(existing.values())
        self.build(new_docs)

    def remove_by_doc_id(self, doc_id: str) -> int:
        """按 doc_id 移除。返回移除数量。"""
        with self._lock:
            before = len(self._docs)
            new_docs = [d for d in self._docs if d.doc_id != doc_id]
            removed = before - len(new_docs)
        if removed:
            self.build(new_docs)
        return removed

    def remove_by_kb_id(self, kb_id: str) -> int:
        with self._lock:
            before = len(self._docs)
            new_docs = [d for d in self._docs if d.kb_id != kb_id]
            removed = before - len(new_docs)
        if removed:
            self.build(new_docs)
        return removed

    def search(
        self,
        query: str,
        top_k: int = 30,
        tenant_id: str | None = None,
        kb_ids: list[str] | None = None,
    ) -> list[tuple[BM25Doc, float]]:
        """检索。

        返回 [(doc, score)]，按 score 降序，score > 0 才返回。
        """
        with self._lock:
            if not self._bm25 or not self._docs:
                return []

            query_tokens = tokenize(query)
            if not query_tokens:
                return []

            scores = self._bm25.get_scores(query_tokens)
            docs = list(self._docs)

        # 过滤 + 打分
        results: list[tuple[BM25Doc, float]] = []
        kb_set = set(kb_ids) if kb_ids else None

        for i, doc in enumerate(docs):
            score = float(scores[i])
            if score <= 0:
                continue
            if tenant_id and doc.tenant_id != tenant_id:
                continue
            if kb_set and doc.kb_id not in kb_set:
                continue
            results.append((doc, score))

        results.sort(key=lambda x: -x[1])
        return results[:top_k]

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._docs)


# 全局单例
_index = BM25Index()


def get_index() -> BM25Index:
    return _index


def is_ready() -> bool:
    return _index.size > 0