from app.worker.pipeline.embedder import embed_query
from app.worker.pipeline.milvus_store import get_client, COLLECTION_NAME
import numpy as np

c = get_client()

# 取一条 chunk 出来
res = c.query(
    collection_name=COLLECTION_NAME,
    filter='chunk_index == 0',
    output_fields=['vector', 'content', 'chunk_id'],
    limit=1,
)
stored = np.array(res[0]['vector'])
content = res[0]['content']
chunk_id = res[0]['chunk_id']

# 用同一个 content 做 query
v_query = np.array(embed_query(content))

# 本地 cosine
local_cos = v_query @ stored
print(f'本地 cos = {local_cos:.6f}')   # 应该接近 1.0

# Milvus search
sr = c.search(
    collection_name=COLLECTION_NAME,
    data=[v_query.tolist()],
    anns_field="vector",
    search_params={"metric_type": "COSINE", "params": {}},
    limit=3,
    output_fields=['chunk_id'],
)
for i, hit in enumerate(sr[0]):
    print(f'  #{i} score={hit.score:.6f}, chunk_id={hit.entity.get("chunk_id")}')