import uuid


def enqueue_ingest_task(doc_id: uuid.UUID) -> uuid.UUID:
    """投递文档解析任务到 Celery，返回 task_id。

    实际项目里 import 你的 Celery app：
        from app.worker.celery_app import celery_app
        task = celery_app.send_task("ingest_document", args=[str(doc_id)])
        return uuid.UUID(task.id)
    """
    from app.worker.tasks import ingest_document

    task = ingest_document.delay(str(doc_id))
    return uuid.UUID(task.id)