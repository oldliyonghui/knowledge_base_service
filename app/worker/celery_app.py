
from celery import Celery
from celery.signals import worker_process_init

from app.core.config import settings

celery_app = Celery(
    "rag_worker",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.worker.tasks"],
)

celery_app.conf.update(
    task_default_queue=settings.celery_task_default_queue,
    task_time_limit=settings.celery_task_time_limit,
    task_soft_time_limit=settings.celery_task_soft_time_limit,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_acks_late=True,                # 任务完成才 ack，防止崩溃丢任务
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,       # 长任务避免一次拿太多
    task_track_started=True,
    result_expires=86400,
)


@worker_process_init.connect
def _on_worker_start(**_kwargs) -> None:
    """Worker 进程启动时确保相关资源就绪。"""
    from app.service.storage import ensure_bucket
    from app.worker.pipeline.milvus_store import ensure_collection

    ensure_bucket()
    ensure_collection()