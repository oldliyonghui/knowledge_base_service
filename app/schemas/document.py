import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.document import DocumentStatus


# ---------- 基础 ----------
class DocumentBase(BaseModel):
    file_name: str = Field(..., max_length=512, description="原始文件名")
    mime_type: str = Field(default="application/pdf", max_length=128)


# ---------- 创建（内部使用，客户端不直接构造） ----------
class DocumentCreate(DocumentBase):
    """上传接口收到文件后，由后端构造，不暴露给客户端。"""

    tenant_id: uuid.UUID
    kb_id: uuid.UUID
    uploader_id: uuid.UUID
    object_key: str
    file_hash: str
    file_size: int


# ---------- 更新 ----------
class DocumentUpdate(BaseModel):
    """允许更新的字段，一般仅内部任务使用。"""

    status: Optional[DocumentStatus] = None
    page_count: Optional[int] = None
    chunk_count: Optional[int] = None
    error_msg: Optional[str] = None
    embedding_model: Optional[str] = None


# ---------- 响应 ----------
class DocumentResponse(DocumentBase):
    """文档详情返回给客户端。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    kb_id: uuid.UUID
    uploader_id: uuid.UUID
    file_size: int
    status: DocumentStatus
    page_count: Optional[int] = None
    chunk_count: Optional[int] = None
    version: int
    embedding_model: Optional[str] = None
    error_msg: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# ---------- 列表项（精简版） ----------
class DocumentListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kb_id: uuid.UUID
    file_name: str
    file_size: int
    status: DocumentStatus
    page_count: Optional[int] = None
    chunk_count: Optional[int] = None
    created_at: datetime


# ---------- 分页 ----------
class DocumentListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[DocumentListItem]


# ---------- 上传响应 ----------
class DocumentUploadResponse(BaseModel):
    """上传接口 202 返回体。"""

    doc_id: uuid.UUID
    # 命中秒传（同知识库已有同名同内容且已入库）时不会投递解析任务，task_id 为空
    task_id: uuid.UUID | None = None
    status: DocumentStatus = DocumentStatus.UPLOADED
    message: str = "文件已上传，正在后台解析"
    # 命中秒传时为 True，前端据此提示「文件已存在」
    deduplicated: bool = False


# ---------- 状态查询 ----------
class DocumentStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    doc_id: uuid.UUID
    status: DocumentStatus
    progress: Optional[float] = Field(
        default=None, ge=0, le=1, description="0~1 的进度，可选"
    )
    error_msg: Optional[str] = None
    updated_at: datetime
