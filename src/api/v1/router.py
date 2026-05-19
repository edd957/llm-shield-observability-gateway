from fastapi import APIRouter

from src.api.v1.endpoints import router as chat_router

api_router = APIRouter(prefix="/v1")
api_router.include_router(chat_router)
