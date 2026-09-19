from fastapi import APIRouter

from app.api import admin_books, audio, auth, books, health, media, questions, reading, realtime, users

v1_router = APIRouter(prefix="/v1")
v1_router.include_router(auth.router)
v1_router.include_router(users.router)
v1_router.include_router(books.router)
v1_router.include_router(reading.router)
v1_router.include_router(audio.router)
v1_router.include_router(questions.router)
v1_router.include_router(realtime.router)
v1_router.include_router(media.router)
v1_router.include_router(admin_books.router)

__all__ = ["health", "v1_router"]
