from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.models.user import Role, User
from app.schemas.role import RoleResponse

router = APIRouter(prefix="/roles", tags=["roles"])


@router.get("", response_model=list[RoleResponse])
async def list_roles(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[RoleResponse]:
    """
    角色字典。用户管理的角色多选、知识库 ACL 的角色主体选择都会用到，
    所以只要有登录态即可访问（只返回 id / code / name，不含敏感信息）。
    """
    roles = (await db.execute(select(Role).order_by(Role.code))).scalars().all()
    return [RoleResponse.model_validate(role) for role in roles]
