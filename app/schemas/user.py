import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserBase(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    email: Optional[EmailStr] = None
    full_name: Optional[str] = Field(default=None, max_length=128)


class UserCreate(UserBase):
    """管理员创建用户时用。"""
    password: str = Field(..., min_length=8, max_length=128)
    tenant_id: uuid.UUID
    dept_id: Optional[uuid.UUID] = None
    role_ids: list[uuid.UUID] = Field(default_factory=list)
    is_active: bool = True
    is_superuser: bool = False


class UserUpdate(BaseModel):
    """管理员更新用户，全部可选。"""
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    dept_id: Optional[uuid.UUID] = None
    role_ids: Optional[list[uuid.UUID]] = None
    is_active: Optional[bool] = None


class AdminPasswordReset(BaseModel):
    """管理员重置他人密码。"""
    new_password: str = Field(..., min_length=8, max_length=128)


class UserSelfUpdate(BaseModel):
    """普通用户改自己的信息。"""
    email: Optional[EmailStr] = None
    full_name: Optional[str] = Field(default=None, max_length=128)


class UserResponse(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    dept_id: Optional[uuid.UUID] = None
    is_active: bool
    is_superuser: bool
    role_ids: list[uuid.UUID] = Field(default_factory=list)
    role_codes: list[str] = Field(default_factory=list)
    last_login_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class UserListResponse(BaseModel):
    """分页响应，字段与 /kbs、/documents 等列表接口保持一致。"""
    total: int
    page: int
    page_size: int
    items: list[UserResponse]
