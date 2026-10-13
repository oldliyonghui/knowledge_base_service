class IngestError(Exception):
    """ingest 流程基础异常。"""


class UnrecoverableIngestError(IngestError):
    """不可重试：PDF 损坏、格式非法、加密无法解密等。"""


class RecoverableIngestError(IngestError):
    """可重试：网络抖动、Milvus 不可用、embedding 限流等。"""