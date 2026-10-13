from pydantic import BaseModel
from typing import Any, List, TypeVar, Generic

T = TypeVar("T")

class Result(BaseModel, Generic[T]):

    code: int = 0
    msg: str = "请求成功"
    data: T | None = None

    @staticmethod
    def success(data=None, msg: str = "操作成功") -> "Result":
        return Result(code=0, data=data, msg=msg)

    @staticmethod
    def failure(code: int = 500, msg: str = "操作失败") -> "Result":
        return Result(code=code, msg=msg)


class PageResult(BaseModel):
    list: List[Any]
    total: int
