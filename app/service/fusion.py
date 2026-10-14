"""多路召回融合：RRF（Reciprocal Rank Fusion）。"""

from typing import Any


def rrf_fusion(
    ranked_lists: list[list[dict]],
    k: int = 60,
    id_key: str = "chunk_id",
) -> list[dict]:
    """Reciprocal Rank Fusion。

    参数：
    - ranked_lists: 多路召回结果，每路是按相关性排序的 dict 列表
    - k: RRF 平滑参数，默认 60（原论文推荐）
    - id_key: 用于识别的唯一键

    返回：
    - 融合后的列表，按 RRF 分数降序，元素保留原始 dict，加 `rrf_score`
    """
    scores: dict[str, float] = {}
    item_map: dict[str, dict] = {}

    for ranked in ranked_lists:
        for rank, item in enumerate(ranked):
            cid = item.get(id_key)
            if not cid:
                continue
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
            # 保留第一次出现的完整信息；后续路只补缺字段
            if cid not in item_map:
                item_map[cid] = dict(item)
            else:
                for key, val in item.items():
                    if key not in item_map[cid] or item_map[cid][key] in (None, ""):
                        item_map[cid][key] = val

    sorted_ids = sorted(scores.items(), key=lambda x: -x[1])
    result = []
    for cid, score in sorted_ids:
        item = item_map[cid]
        item["rrf_score"] = score
        result.append(item)
    return result