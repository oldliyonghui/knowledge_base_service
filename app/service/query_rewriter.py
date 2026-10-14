"""Query 改写：把复杂问题拆成多个检索友好的子查询。"""

import logging
import re
from functools import lru_cache

from app.core.config import settings
from app.service.llm import chat_completion

logger = logging.getLogger(__name__)

REWRITE_PROMPT = """你是检索助手。把用户的宽泛问题拆成 3~4 个**具体的、可单独检索的**子问题。

核心原则：
- 每条子问题必须"具体到某一个点"，不能是原问题的同义改写
- 每条都能在文档里找到对应的具体条目
- 不要输出"XXX有哪些"、"XXX包括什么"这类聚合问题
- 拆 3~4 条，尽量覆盖不同方面
- **如果用户问题是英文，先翻译成中文再改写**

示例：
用户问题：维护保养都有哪些方面
输出：
滤网多久清洗一次
边刷如何清理
尘盒怎么保养
主刷如何维护

现在改写下面的问题：

用户问题：{question}

子问题（一行一条，3~4 条）："""


# 聚合词：出现这些词，说明用户想"汇总多个方面"，必须改写
_AGGREGATE_WORDS = [
    "哪些", "都有", "分别", "几个方面", "有什么",
    "总结", "归纳", "包括", "列举", "介绍一下",
]

# 检测是否含英文字母
_HAS_ASCII_LETTER = re.compile(r"[a-zA-Z]")


def _is_simple(question: str) -> bool:
    """判断是否简单问题。简单的不改写。

    规则：
    1. 含聚合词 → 改写
    2. 含英文（需要翻译）→ 改写
    3. 其他 → 不改写
    """
    q = question.strip()

    # 聚合词：需要拆多路
    if any(w in q for w in _AGGREGATE_WORDS):
        return False

    # 含英文：需要翻译成中文
    if _HAS_ASCII_LETTER.search(q):
        return False

    return True

def _clean_line(line: str) -> str:
    """去掉行首的编号、破折号、引号。"""
    line = line.strip()
    # 去掉 "1. " "1) " "1、 " "- " "• "
    line = re.sub(r"^[\d]+[\.\)、]\s*", "", line)
    line = re.sub(r"^[-•*]\s*", "", line)
    # 去掉首尾引号
    line = line.strip("\"'“”‘’")
    return line.strip()


def _deduplicate(items: list[str]) -> list[str]:
    """保序去重。"""
    seen = set()
    result = []
    for x in items:
        key = x.lower()
        if key not in seen:
            seen.add(key)
            result.append(x)
    return result


def rewrite_query(question: str) -> list[str]:
    """把用户问题改写成多个检索 query。

    - 简单问题：返回 [原问题]
    - 复杂问题：返回 [改写1, 改写2, ...] + 原问题（保底）
    - LLM 失败：返回 [原问题]
    """
    if not settings.rag_query_rewrite_enabled:
        return [question]

    if _is_simple(question):
        logger.debug("query 简单，不改写: %s", question)
        return [question]

    try:
        resp = chat_completion(
            messages=[
                {"role": "system", "content": "你只输出改写后的检索查询，一行一条，不加解释"},
                {"role": "user", "content": REWRITE_PROMPT.format(question=question)},
            ],
            temperature=0.3,
            max_tokens=200,
        )
        raw = resp.content or ""
    except Exception as e:
        logger.warning("query 改写失败: %s，回退到原 query", e)
        return [question]

    lines = [_clean_line(l) for l in raw.split("\n") if l.strip()]
    lines = [l for l in lines if len(l) >= 2]
    lines = _deduplicate(lines)

    # 去掉 LLM 可能重复输出的原问题
    lines = [l for l in lines if l != question]

    if not lines:
        return [question]

    result = lines + [question]

    max_n = settings.rag_query_rewrite_max
    result = result[:max_n]

    logger.info("query 改写: %s -> %s", question, result)
    return result