# knowledge_base_service
# RAG 知识库服务

基于 FastAPI + Milvus + 通义千问的企业级 RAG（检索增强生成）知识库系统。

上传 PDF → 自动解析分块 → 向量化入库 → 语义检索 → 大模型生成带引用的回答。

## 目录

- [功能特性](#功能特性)
- [技术栈](#技术栈)
- [系统架构](#系统架构)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [API 文档](#api-文档)
- [项目结构](#项目结构)

## 功能特性

### 用户与权限
- JWT 认证（access + refresh token 轮换）
- 多租户隔离（tenant_id）
- 知识库级 ACL（用户/部门/角色三级授权）
- 三级权限：read / write / admin

### 文档管理
- PDF 上传（异步解析，不阻塞请求）
- 自动解析、分块、向量化、入库
- FAQ 类文档智能分块（一问一答）
- 文档去重（SHA256 秒传）
- 文档删除（清理 Milvus 向量 + MinIO 文件）
- 处理状态实时查询

### 检索与问答
- Milvus 向量检索（cosine 相似度）
- 通义 `gte-rerank-v2` 精排
- 相对阈值 + 绝对阈值双重过滤
- 带引用回答（chunk_id、文档名、页码、分数）
- 流式输出（SSE）
- 多轮对话（历史上下文）
- 会话管理（创建/列表/删除/历史）

### 工程特性
- Celery 异步任务（解析/删除/清理）
- 幂等任务（重跑安全）
- 可重试 / 不可重试异常分级
- 结构化日志
- Docker Compose 一键起依赖
- systemd 常驻应用层

## 技术栈

| 层 | 技术 |
|---|---|
| Web 框架 | FastAPI 0.115+ |
| ORM | SQLAlchemy 2.0 (async) |
| 数据库 | MySQL 8.0 |
| 缓存/队列 | Redis 7 |
| 向量库 | Milvus 2.4 |
| 对象存储 | MinIO (pgsty/silo) |
| 异步任务 | Celery 5.4 |
| LLM | 通义千问 qwen-plus |
| Embedding | 通义 text-embedding-v3 (1024维) |
| Rerank | 通义 gte-rerank-v2 |
| LangChain | langchain-openai / langchain-community |
| 认证 | PyJWT + argon2 |
| 部署 | Docker Compose + systemd + Nginx |

## 系统架构

                        ┌──────────────────────────┐
                        │        客户端             │
                        │  Web / Streamlit / App   │
                        └────────────┬─────────────┘
                                     │
                                     │ HTTPS
                                     ▼
                        ┌──────────────────────────┐
                        │         Nginx            │
                        │   反向代理 / HTTPS 终止     │
                        └────────────┬─────────────┘
                                     │
                                     │ HTTP (127.0.0.1:8000)
                                     ▼
       ┌─────────────────────────────────────────────────────────┐
       │                       FastAPI                           │
       │                                                         │
       │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐ │
       │  │  Auth    │  │   KB     │  │   Doc    │  │  Chat    │ │
       │  └──────────┘  └──────────┘  └──────────┘  └──────────┘ │
       └────────┬─────────────────────────────────┬──────────────┘
                │                                 │
                │ 投递任务                         │ 检索
                ▼                                 ▼
       ┌──────────────────┐              ┌──────────────────┐
       │  Celery Worker   │              │     Milvus       │
       │  异步任务处理       │              │  向量库 (19530)   │
       └────────┬─────────┘              └──────────────────┘
                │                                ▲
                │ 解析 / embedding / 写入          │
                │                                │
                ▼                                │
   ┌────────────────────┬────────────────────┬───┴────────────────┐
   │      MySQL         │       MinIO        │       Redis        │
   │  业务数据 / 权限      │   PDF 文件存储      │  队列 / 缓存         │
   │      (3306)        │      (9000)        │      (6379)        │
   └────────────────────┴────────────────────┴────────────────────┘


**数据流**：
上传 PDF
→ FastAPI 存文件到 MinIO
→ 落 MySQL documents 记录
→ 投递 Celery 任务
→ Worker: 下载 → 解析 → 分块 → embedding → 写 Milvus
→ 更新状态为 indexed

提问
→ FastAPI 检索 Milvus（带权限过滤）
→ rerank 精排
→ 组装 prompt 调通义千问
→ 落 MySQL 消息 + citations
→ 返回答案 + 引用

text

## 快速开始

### 环境要求

- Docker 20.10+
- Docker Compose 2.0+
- Python 3.12
- 服务器内存 ≥ 8G（Milvus 需要）

### 本地开发

```bash
# 1. 克隆代码
git clone https://github.com/你的用户名/ragService.git
cd ragService

# 2. 起依赖服务
docker compose up -d
docker compose ps   # 等 Milvus healthy

# 3. 建 Python 环境
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 4. 配环境变量
cp .env.example .env
vim .env   # 填入 DASHSCOPE_API_KEY 等

# 5. 建表 + 建 Collection
python -m scripts.create_all
python -m scripts.init_milvus

# 6. 建初始 admin（DEBUG=false 时手动）
python -c "
import asyncio
from app.bootstrap import ensure_admin_user
from app.db.session import async_session_factory

async def main():
    async with async_session_factory() as db:
        await ensure_admin_user(db)

asyncio.run(main())
"

# 7. 起 FastAPI（终端 1）
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 8. 起 Celery（终端 2）
python -m celery -A app.worker.celery_app.celery_app worker \
  --loglevel=INFO --pool=solo
验证：

bash
curl -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123456"}'
返回 access_token 就成功了。

配置说明

所有配置通过环境变量或 .env 文件提供。
必填项

变量	说明
DASHSCOPE_API_KEY	通义千问 API Key（必填）
JWT_SECRET_KEY	JWT 签名密钥，强随机字符串
DATABASE_URL	MySQL 异步连接串
DATABASE_URL_SYNC	MySQL 同步连接串（Worker 用）
CELERY_BROKER_URL	Redis broker
MILVUS_URI	Milvus 地址
S3_ENDPOINT	MinIO 地址（不带 http://）
关键配置项

dotenv
# 运行模式
DEBUG=false                          
BOOTSTRAP_ENABLED=false              # 生产关闭自动建 admin

# 数据库（密码和 docker-compose.yml 一致）
DATABASE_URL=mysql+aiomysql://root:密码@127.0.0.1:3306/rag?charset=utf8mb4
DATABASE_URL_SYNC=mysql+pymysql://root:密码@127.0.0.1:3306/rag?charset=utf8mb4

# Celery
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/1

# 通义千问
DASHSCOPE_API_KEY=sk-xxx(示例)
EMBEDDING_MODEL=text-embedding-v3(示例)
EMBEDDING_DIM=1024                   # 
EMBEDDING_BATCH_SIZE=16              # 本地调试用小值

LLM_MODEL=qwen-plus(示例)
LLM_MAX_TOKENS=2048
LLM_TEMPERATURE=0.2

# RAG 检索
RAG_COARSE_TOP_K=30                  # 粗排召回数
RAG_TOP_K=5                          # 最终返回数
RAG_RERANK_ENABLED=true
RAG_RERANK_MIN_SCORE=0.5             # rerank 阈值

# Milvus
MILVUS_URI=http://127.0.0.1:19530
MILVUS_COLLECTION=knowledge_chunks

# MinIO
S3_ENDPOINT=127.0.0.1:9000           #
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
S3_BUCKET=rag-docs
S3_SECURE=false


启动后访问 http://127.0.0.1:8000/docs 查看交互式 API 文档。

核心接口

认证

方法	路径	说明
POST	/api/v1/auth/login	登录
POST	/api/v1/auth/refresh	刷新 token
POST	/api/v1/auth/logout	登出
GET	/api/v1/auth/me	当前用户
POST	/api/v1/auth/change-password	改密码
知识库

方法	路径	说明
POST	/api/v1/kbs	创建知识库
GET	/api/v1/kbs	我的知识库列表
GET	/api/v1/kbs/{id}	知识库详情
PATCH	/api/v1/kbs/{id}	更新
DELETE	/api/v1/kbs/{id}	删除（需 ADMIN）
GET	/api/v1/kbs/{id}/my-permission	我的权限
POST	/api/v1/kbs/{id}/acls	授权给用户/角色/部门
DELETE	/api/v1/kbs/{id}/acls/{acl_id}	撤销授权
文档

方法	路径	说明
POST	/api/v1/kbs/{kb_id}/documents/upload	上传 PDF（返回 202）
GET	/api/v1/documents	文档列表
GET	/api/v1/documents/{id}	文档详情
GET	/api/v1/documents/{id}/status	处理状态（轮询）
DELETE	/api/v1/documents/{id}	删除文档
问答

方法	路径	说明
POST	/api/v1/chat/sessions	创建会话
GET	/api/v1/chat/sessions	会话列表
GET	/api/v1/chat/sessions/{id}/messages	历史消息
POST	/api/v1/chat/sessions/{id}/messages	提问
POST	/api/v1/chat/sessions/{id}/messages/stream	流式提问（SSE）
DELETE	/api/v1/chat/sessions/{id}	删除会话
POST	/api/v1/chat/messages/{id}/feedback	点赞/点踩
使用示例

完整流程：

bash
# 1. 登录
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123456"}' \
  | jq -r .access_token)

# 2. 建知识库
KB_ID=$(curl -s -X POST http://127.0.0.1:8000/api/v1/kbs \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"测试知识库","visibility":"private"}' \
  | jq -r .id)

# 3. 上传 PDF
DOC_ID=$(curl -s -X POST http://127.0.0.1:8000/api/v1/kbs/$KB_ID/documents/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@test.pdf" \
  | jq -r .doc_id)

# 4. 轮询状态
while true; do
  STATUS=$(curl -s http://127.0.0.1:8000/api/v1/documents/$DOC_ID/status \
    -H "Authorization: Bearer $TOKEN" | jq -r .status)
  echo "$STATUS"
  [ "$STATUS" = "indexed" ] && break
  [ "$STATUS" = "failed" ] && break
  sleep 3
done

# 5. 建会话
SESSION_ID=$(curl -s -X POST http://127.0.0.1:8000/api/v1/chat/sessions \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"title\":\"测试\",\"kb_ids\":[\"$KB_ID\"]}" \
  | jq -r .id)

# 6. 提问
curl -s -X POST http://127.0.0.1:8000/api/v1/chat/sessions/$SESSION_ID/messages \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question":"这份文档讲了什么？"}' | jq
流式提问：

bash
curl -N -X POST http://127.0.0.1:8000/api/v1/chat/sessions/$SESSION_ID/messages/stream \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question":"详细讲讲","stream":true}'
项目结构

text
ragService/
├── app/
│   ├── main.py                    # FastAPI 入口
│   ├── bootstrap.py               # 初始化 admin
│   ├── api/                       # 路由层
│   │   ├── auth.py
│   │   ├── users.py
│   │   ├── kbs.py
│   │   ├── documents.py
│   │   └── chat.py
│   ├── core/
│   │   ├── config.py              # 配置定义
│   │   ├── security.py            # 密码哈希 + JWT
│   │   └── deps.py                # 依赖注入
│   ├── db/
│   │   └── session.py             # 异步 session
│   ├── models/                    # SQLAlchemy 模型
│   │   ├── base.py
│   │   ├── types.py               # GUID / EnumStr
│   │   ├── user.py
│   │   ├── knowledge_base.py
│   │   ├── kb_acl.py
│   │   ├── document.py
│   │   ├── document_chunk.py
│   │   └── chat.py
│   ├── schemas/                   # Pydantic 模型
│   ├── services/                  # 业务逻辑
│   │   ├── auth_service.py
│   │   ├── permission.py          # 权限校验
│   │   ├── kb_service.py
│   │   ├── document_service.py
│   │   ├── chat_service.py
│   │   ├── rag_service.py         # RAG 编排
│   │   ├── retrieval.py           # 检索
│   │   ├── reranker.py            # 精排
│   │   ├── llm.py                 # LLM 客户端
│   │   └── storage.py             # MinIO 封装
│   └── worker/                    # Celery Worker
│       ├── celery_app.py
│       ├── db.py
│       ├── exceptions.py
│       ├── tasks.py
│       └── pipeline/
│           ├── pdf_parser.py      # PDF 解析
│           ├── chunker.py         # 分块
│           ├── embedder.py        # embedding
│           └── milvus_store.py    # Milvus 读写
├── scripts/
│   ├── create_all.py              # 建表
│   ├── init_milvus.py             # 建 Collection
│   ├── eval_retrieval.py          # 检索评估
│   └── eval_cases.py              # 评估用例
├── web/
│   └── app.py                     # Streamlit 调试台
├── docker-compose.yml             # 依赖服务
├── requirements.txt
├── .env.example
└── README.md


#后续规划
□ Query 改写（LLM 拆解多主题问题）
□ 混合检索（向量 + BM25）
□ Redis 缓存（可读 kb 列表、embedding 结果）
□ 文档级 ACL


作者：enslivan
邮箱：18335103323@163.com


