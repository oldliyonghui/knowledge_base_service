import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.kb_acl import AclPermission, AclSubjectType


class KBAclBase(BaseModel):
    subject_type: AclSubjectType
    subject_id: uuid.UUID
    permission: AclPermission = AclPermission.READ


class KBAclCreate(KBAclBase):
    """授予某个主体权限。"""


class KBAclUpdate(BaseModel):
    permission: AclPermission


class KBAclResponse(KBAclBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kb_id: uuid.UUID
    granted_by: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime


class KBAclListResponse(BaseModel):
    total: int
    items: list[KBAclResponse]


class MyPermissions(BaseModel):
    """当前用户对某知识库的最终权限。"""

    kb_id: uuid.UUID
    can_read: bool
    can_write: bool
    can_admin: bool
    reason: str = Field(
        ...,
        description="owner / visibility / acl:dept / acl:role / acl:user / none",
    )