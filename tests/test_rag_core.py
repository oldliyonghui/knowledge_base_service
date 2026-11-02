"""RAG 核心逻辑的单元测试。

全部是纯函数：不连数据库、不调外部 API，几秒跑完。
覆盖这些决定：引用钳制、prompt 结构、RRF 排序、rerank 过滤分支、权限等级、采样参数。
"""

import uuid

from app.models.chat import ChatMessage, MessageRole
from app.models.kb_acl import AclPermission, AclSubjectType, KBAcl
from app.service.fusion import rrf_fusion
from app.service.kb_acl_service import has_permission, max_permission
from app.service.llm import _sampling_kwargs
from app.service.permission import build_milvus_acl_filter
from app.service.query_rewriter import _is_simple
from app.service.rag_service import (
    _build_context,
    _build_messages,
    normalize_citations_in_answer,
)
from app.service.retrieval import RetrievedChunk, apply_rerank_filter


def make_chunk(content: str, score: float = 0.9, page: int | None = 1) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        doc_id=uuid.uuid4(),
        kb_id=uuid.uuid4(),
        content=content,
        score=score,
        page_start=page,
        page_end=page,
        section_title=None,
        file_name="test.pdf",
    )


# ---------- 引用编号 ----------

def test_citations_removed_when_no_source():
    assert normalize_citations_in_answer("答案见[1]和[2]", 0) == "答案见和"


def test_citations_clamped_to_range():
    assert normalize_citations_in_answer("见[0][9]", 3) == "见[1][3]"


def test_citations_untouched_when_valid():
    assert normalize_citations_in_answer("见[2]", 3) == "见[2]"


# ---------- 上下文与 prompt 结构 ----------

def test_build_context_numbers_chunks():
    ctx = _build_context([make_chunk("第一段"), make_chunk("第二段")])
    assert "[1]" in ctx and "[2]" in ctx
    assert "第一段" in ctx and "第二段" in ctx


def test_build_context_empty():
    assert _build_context([]) == "（无相关检索结果）"


def test_build_messages_keeps_context_out_of_system():
    history = [
        ChatMessage(role=MessageRole.USER, content="上一轮问题"),
        ChatMessage(role=MessageRole.ASSISTANT, content="上一轮回答"),
    ]
    msgs = _build_messages("本轮问题", [make_chunk("检索到的事实")], history)

    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user"]
    assert sum(1 for m in msgs if m["role"] == "system") == 1
    assert "<context>" not in msgs[0]["content"]
    assert "<context>" in msgs[-1]["content"]
    assert "检索到的事实" in msgs[-1]["content"]
    assert "本轮问题" in msgs[-1]["content"]


# ---------- RRF 融合 ----------

def test_rrf_prefers_documents_in_both_lists():
    list_a = [{"chunk_id": "x"}, {"chunk_id": "y"}]
    list_b = [{"chunk_id": "y"}, {"chunk_id": "z"}]
    fused = rrf_fusion([list_a, list_b], k=60)
    assert [h["chunk_id"] for h in fused] == ["y", "x", "z"]


# ---------- rerank 过滤 ----------

def test_rerank_filter_keeps_above_threshold():
    hits = [
        {"content": "a", "score": 0.9},
        {"content": "b", "score": 0.8},
        {"content": "c", "score": 0.1},
    ]
    reranked = [(0, 0.9), (1, 0.8), (2, 0.1)]
    out = apply_rerank_filter(hits, reranked, top_k=3, min_score=0.5)
    assert [h["content"] for h in out] == ["a", "b"]
    assert out[0]["rerank_score"] == 0.9


def test_rerank_filter_returns_empty_when_all_low():
    hits = [{"content": "a", "score": 0.3}]
    assert apply_rerank_filter(hits, [(0, 0.2)], top_k=3, min_score=0.5) == []


def test_rerank_filter_falls_back_without_rerank():
    hits = [{"content": "a"}, {"content": "b"}, {"content": "c"}]
    out = apply_rerank_filter(hits, [], top_k=2, min_score=0.5)
    assert [h["content"] for h in out] == ["a", "b"]
    assert "rerank_score" not in out[0]


def test_rerank_filter_does_not_mutate_input():
    hits = [{"content": "a", "score": 0.9}]
    out = apply_rerank_filter(hits, [(0, 0.9)], top_k=1, min_score=0.1)
    assert "rerank_score" not in hits[0]
    assert out[0]["rerank_score"] == 0.9


# ---------- 权限与检索过滤 ----------

def test_permission_level_ordering():
    assert has_permission(AclPermission.WRITE, AclPermission.READ)
    assert has_permission(AclPermission.ADMIN, AclPermission.WRITE)
    assert not has_permission(AclPermission.READ, AclPermission.WRITE)
    assert not has_permission(None, AclPermission.READ)


def test_max_permission_picks_highest():
    acls = [
        KBAcl(
            subject_type=AclSubjectType.USER,
            subject_id=uuid.uuid4(),
            permission=AclPermission.READ,
        ),
        KBAcl(
            subject_type=AclSubjectType.USER,
            subject_id=uuid.uuid4(),
            permission=AclPermission.ADMIN,
        ),
    ]
    assert max_permission(acls) == AclPermission.ADMIN


def test_milvus_filter_blocks_all_without_readable_kb():
    expr = build_milvus_acl_filter(tenant_id=uuid.uuid4(), readable_kb_ids=[])
    assert "__none__" in expr


def test_milvus_filter_contains_tenant_and_kbs():
    tenant = uuid.uuid4()
    kb1, kb2 = uuid.uuid4(), uuid.uuid4()
    expr = build_milvus_acl_filter(tenant_id=tenant, readable_kb_ids=[kb1, kb2])
    assert f'tenant_id == "{tenant}"' in expr
    assert str(kb1) in expr and str(kb2) in expr


# ---------- LLM 采样参数 ----------

def test_sampling_kwargs_with_max_tokens():
    assert _sampling_kwargs(0.3, 128) == {"temperature": 0.3, "max_tokens": 128}


def test_sampling_kwargs_omits_none_max_tokens():
    assert _sampling_kwargs(0.3, None) == {"temperature": 0.3}


# ---------- query 改写判定 ----------

def test_is_simple_detection():
    assert _is_simple("滤网多久换一次")
    assert not _is_simple("维护保养都有哪些方面")
    assert not _is_simple("robot vacuum wifi setup")