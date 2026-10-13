"""检索质量评估脚本。

用法：
    python -m scripts.eval_retrieval                    # 用当前 config 跑一遍
    python -m scripts.eval_retrieval --top-k 5          # 指定 top_k
    python -m scripts.eval_retrieval --no-rerank        # 关掉 rerank 对比
    python -m scripts.eval_retrieval --verbose          # 打印每条命中的内容

指标：
    Hit@K       前 K 条里是否命中期望词
    MRR         命中位置的倒数（越靠前越高）
    平均延迟     单次检索耗时
    平均 rerank  目标 chunk 的 rerank 分数
"""

import argparse
import statistics
import time
import uuid
from dataclasses import dataclass

from app.core.config import settings
from app.service.reranker import rerank
from app.service.retrieval import _embed_query, _milvus_search, apply_rerank_filter
from scripts.eval_cases import EVAL_CASES


# ============ 配置区（按你的环境改） ============
TENANT_ID = "00000000-0000-0000-0000-000000000001"
KB_ID = "de84ce72-6308-4ce5-8a5b-4501668ab377"   # ← 你的 KB ID
# ==============================================


@dataclass
class CaseResult:
    query: str
    category: str
    hit: bool
    rank: int | None         # 命中位置（1-based），未命中为 None
    latency_ms: float
    top_score: float         # 最高 rerank 分数
    target_score: float | None  # 目标 chunk 的 rerank 分数
    total_hits: int          # 返回条数
    expect_empty: bool


def build_filter(kb_id: str, tenant_id: str) -> str:
    return f'tenant_id == "{tenant_id}" and kb_id in ["{kb_id}"]'


def search_once(query, filter_expr, top_k, use_rerank, coarse_k=30, verbose=False):
    t0 = time.perf_counter()

    query_vector = _embed_query(query)
    hits = _milvus_search(query_vector, filter_expr, coarse_k)

    if not hits:
        return [], (time.perf_counter() - t0) * 1000, []

    if use_rerank and len(hits) > top_k:
        docs = [h["content"] for h in hits]
        reranked = rerank(query, docs, top_n=top_k)
        # ← 直接调用公共函数
        final = apply_rerank_filter(
            hits, reranked, top_k, settings.rag_rerank_min_score
        )
        latency = (time.perf_counter() - t0) * 1000
        return final, latency, reranked
    else:
        hits = hits[:top_k]
        latency = (time.perf_counter() - t0) * 1000
        return hits, latency, []


def evaluate_case(case: dict, filter_expr: str, top_k: int, use_rerank: bool, verbose: bool) -> CaseResult:
    query = case["query"]
    expect_keywords = case.get("expect_keywords", [])
    expect_empty = case.get("expect_empty", False)
    min_hits = case.get("min_hits", 1)

    final, latency, reranked = search_once(
        query, filter_expr, top_k, use_rerank, verbose=verbose
    )

    # 找命中位置
    rank = None
    target_score = None
    for i, h in enumerate(final, 1):
        content = h["content"]
        if any(kw in content for kw in expect_keywords):
            rank = i
            target_score = h.get("rerank_score")
            break

    # 判断是否通过
    if expect_empty:
        hit = len(final) == 0
    else:
        hit = rank is not None and len(final) >= min_hits

    # 打印
    mark = "✅" if hit else "❌"
    cat = case.get("category", "-")
    info = f"rank={rank}" if rank else "未命中"
    score_info = f" target={target_score:.3f}" if target_score else ""
    print(f"  {mark} [{cat}] {query}")
    print(f"       返回 {len(final)} 条 · {info}{score_info} · {latency:.0f}ms")

    if verbose:
        for i, h in enumerate(final, 1):
            preview = h["content"].replace("\n", " ")[:70]
            rs = h.get("rerank_score")
            rs_str = f"rerank={rs:.3f}" if rs is not None else f"cos={h['score']:.3f}"
            print(f"       [{i}] {rs_str}  {preview}")

    return CaseResult(
        query=query,
        category=cat,
        hit=hit,
        rank=rank,
        latency_ms=latency,
        top_score=final[0].get("rerank_score", 0) if final else 0,
        target_score=target_score,
        total_hits=len(final),
        expect_empty=expect_empty,
    )


def summarize(results: list[CaseResult]) -> None:
    total = len(results)
    hits = sum(1 for r in results if r.hit)
    hit_rate = hits / total if total else 0

    # MRR（只统计非 expect_empty 的）
    valid = [r for r in results if not r.expect_empty]
    mrr = 0.0
    if valid:
        mrr = sum((1.0 / r.rank) if r.rank else 0.0 for r in valid) / len(valid)

    # 平均延迟
    latencies = [r.latency_ms for r in results]
    avg_latency = statistics.mean(latencies) if latencies else 0

    # 平均返回条数（非 expect_empty）
    avg_hits = statistics.mean([r.total_hits for r in valid]) if valid else 0

    print("\n" + "=" * 60)
    print("汇总")
    print("=" * 60)
    print(f"  总用例:      {total}")
    print(f"  命中数:      {hits}")
    print(f"  Hit Rate:    {hit_rate:.1%}")
    print(f"  MRR:         {mrr:.3f}")
    print(f"  平均延迟:    {avg_latency:.0f}ms")
    print(f"  平均返回条数: {avg_hits:.1f}")

    # 按分类汇总
    by_cat = {}
    for r in results:
        by_cat.setdefault(r.category, []).append(r)

    print("\n  按分类:")
    for cat, rs in by_cat.items():
        h = sum(1 for r in rs if r.hit)
        print(f"    [{cat}] {h}/{len(rs)} ({h/len(rs):.0%})")

    # 失败用例
    failures = [r for r in results if not r.hit]
    if failures:
        print("\n  未通过:")
        for r in failures:
            print(f"    ❌ [{r.category}] {r.query}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--no-rerank", action="store_true", help="关掉 rerank 对比")
    parser.add_argument("--verbose", "-v", action="store_true", help="打印每条命中内容")
    parser.add_argument("--kb", default=KB_ID, help="知识库 ID")
    parser.add_argument("--tenant", default=TENANT_ID, help="租户 ID")
    args = parser.parse_args()

    use_rerank = not args.no_rerank
    filter_expr = build_filter(args.kb, args.tenant)

    print("=" * 60)
    print(f"检索评估 | top_k={args.top_k} | rerank={'ON' if use_rerank else 'OFF'}")
    print(f"filter: {filter_expr}")
    print("=" * 60)

    results = []
    for case in EVAL_CASES:
        query = case["query"]
        if len(query) > 2000:
            print(f"  跳过（query 太长）: {query[:50]}...")
            continue
        r = evaluate_case(case, filter_expr, args.top_k, use_rerank, args.verbose)
        results.append(r)

    summarize(results)


if __name__ == "__main__":
    main()