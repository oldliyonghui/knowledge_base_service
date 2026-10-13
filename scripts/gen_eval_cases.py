# scripts/gen_eval_cases.py
"""一次性脚本：从 Milvus 里抽 chunk，让 LLM 生成评估用例。

生成后人工筛选，保留带独特关键词的。
"""
import json
import random

from app.service.llm import chat_completion
from app.worker.pipeline.milvus_store import get_client, COLLECTION_NAME

KB_ID = "de84ce72-6308-4ce5-8a5b-4501668ab377"  # 改成你的

PROMPT_TEMPLATE = """你是一个测试工程师。下面是一段知识库内容，请生成 2 个用户可能问的问题。

要求：
1. 问题要口语化，像真实用户提问
2. 输出 JSON 数组，每项格式：
   {"query": "用户问题", "expect_keywords": ["答案里最有辨识度的词"]}

内容：
{content}

只输出 JSON 数组本身，不要任何解释、不要 markdown 代码块。"""


def main():
    c = get_client()
    res = c.query(
        collection_name=COLLECTION_NAME,
        filter=f'kb_id == "{KB_ID}"',
        output_fields=["content", "chunk_index"],
        limit=1000,
    )
    random.shuffle(res)

    all_cases = []
    for i, r in enumerate(res[:30]):  # 抽 30 条
        try:
            # 用 replace 替代 format，不影响 JSON 里的花括号
            prompt = PROMPT_TEMPLATE.replace("{content}", r["content"])
            resp = chat_completion([
                {"role": "system", "content": "你只输出 JSON"},
                {"role": "user", "content": prompt},
            ], temperature=0.7)
            text = resp.content.strip()
            # 去掉可能的 ```json 包裹
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            cases = json.loads(text)
            for c_item in cases:
                c_item["category"] = "单一事实"
                c_item["_source_chunk"] = r["content"][:50]
                all_cases.append(c_item)
            print(f"[{i}] 生成 {len(cases)} 条")
        except Exception as e:
            print(f"[{i}] 失败: {type(e).__name__}: {e}")

    # 输出
    with open("scripts/eval_cases_generated.py", "w", encoding="utf-8") as f:
        f.write("EVAL_CASES = [\n")
        for c_item in all_cases:
            f.write(f"    {json.dumps(c_item, ensure_ascii=False)},\n")
        f.write("]\n")
    print(f"\n共 {len(all_cases)} 条，已写入 scripts/eval_cases_generated.py")


if __name__ == "__main__":
    main()