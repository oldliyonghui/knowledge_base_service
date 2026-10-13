from fastapi import APIRouter

from app.api import auth, documents, users, kbs, chat

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(auth.router)
api_router.include_router(users.router)

api_router.include_router(kbs.router)
api_router.include_router(documents.router)
api_router.include_router(chat.router)