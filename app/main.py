import uvicorn
from fastapi import FastAPI
from fastapi.exceptions import ValidationException
from fastapi.responses import JSONResponse
from fastapi import HTTPException
from contextlib import asynccontextmanager

from app.api import api_router
from app.core.config import settings
from app.core.exceptions import BizException, biz_exception_handler, http_exception_handler, validation_exception_handler
import logging
from app.bootstrap import bootstrap

class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"

logging.basicConfig(
    level=logging.INFO if not settings.debug else logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ---- 启动 ----
    if settings.debug:
        await bootstrap()

    yield

    # ---- 关闭 ----
    # 有需要清理的资源（redis、http client 等）放这里


app = FastAPI(title="My FastAPI App", debug=settings.debug, lifespan=lifespan)

app.add_exception_handler(BizException, biz_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(ValidationException, validation_exception_handler)

#api路由
app.include_router(api_router)

@app.get("/")
async def root():
    return {"message": "Hello 123"}

@app.get("/hello/{name}")
async def say_hello(name: str):
    return {"message": f"Hello {name}"}

if __name__ == "__main__":
    #启动
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
