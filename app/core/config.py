from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2] #项目根目录

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "rag-service"
    api_prefix: str = "/api/"
    debug: bool = True
    #mysql
    database_url: str = "mysql+aiomysql://root:root@127.0.0.1:3306/rag?charset=utf8mb4"
    database_url_sync: str = "mysql+pymysql://root:root@127.0.0.1:3306/rag?charset=utf8mb4"
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle: int = 1800

    # jwt
    jwt_secret_key: str = "change-me-in-production"
    jwt_access_expire_minutes: int = 120
    jwt_refresh_expire_days: int = 14

    # 本地调试初始化
    bootstrap_enabled: bool = True
    bootstrap_tenant_id: str = "00000000-0000-0000-0000-000000000001"
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: str = "admin123456"
    bootstrap_admin_email: str = "admin@example.com"
    bootstrap_admin_full_name: str = "Administrator"

    # ---------- Celery ----------
    # 本地默认用 Redis
    celery_broker_url: str = "redis://127.0.0.1:6379/0"
    celery_result_backend: str = "redis://127.0.0.1:6379/1"
    celery_task_default_queue: str = "celery"
    celery_task_time_limit: int = 1800  # 单任务硬超时（秒）
    celery_task_soft_time_limit: int = 1500  # 单任务软超时（秒）

    # ---------- Embedding ----------
    embedding_model: str = "text-embedding-v4"
    embedding_dim: int = 1024
    embedding_batch_size: int = 32

    # ---------- LLM ----------
    llm_model: str = "qwen3.7-max"
    llm_max_tokens: int = 2048
    llm_temperature: float = 0.2
    dashscope_api_key: str = ""

    # ---------- RAG ----------
    rag_top_k: int = 5
    rag_max_context_tokens: int = 6000
    rag_history_turns: int = 6
    rag_rerank_enabled: bool = True
    rag_rerank_model: str = "qwen3-rerank"
    rag_coarse_top_k: int = 30  # 粗排召回数
    rag_min_score: float = 0.0  # 粗排最低分（放宽，让 rerank 挑）
    rag_rerank_min_score: float = 0.5  # rerank 后的最低分

    # ---------- 分块 ----------
    chunk_size: int = 512
    chunk_overlap: int = 64
    chunk_min_chars: int = 30

    # ---------- 上传 ----------
    max_upload_size_mb: int = 100
    allowed_mime_types: list[str] = ["application/pdf"]

    # ---------- MinIO / S3 ----------
    s3_endpoint: str = "127.0.0.1:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "rag-docs"
    s3_secure: bool = False
    s3_region: str | None = None

    # ---------- Milvus ----------
    milvus_uri: str = "http://127.0.0.1:19530"
    milvus_token: str = ""
    milvus_collection: str = "knowledge_chunks"
    milvus_metric_type: str = "COSINE"
    milvus_index_type: str = "AUTOINDEX"

    cors_origins: list[str] = ["*"]

settings = Settings()
