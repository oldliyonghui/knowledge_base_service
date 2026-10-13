from http import HTTPStatus

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from app.schemas.response import Result

class BizException(Exception):

    def __init__(self, code: int, msg: str):
        self.code = code
        self.msg = msg

async def biz_exception_handler(request: Request, exc: BizException) -> JSONResponse:
    return JSONResponse(
        status_code=200,
        content=Result.failure(code=exc.code, msg=exc.msg).model_dump(),
    )

async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    print(f"响应错误：{exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content=Result.failure(code=exc.status_code, msg=str(exc.detail)).model_dump(),
    )

async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    msg = errors[0].get("msg", "参数校验失败") if errors else "参数校验失败"
    return JSONResponse(
        status_code=422,
        content=Result.failure(code=422, msg=msg).model_dump(),
    )