"""Versioned API router composition."""

from fastapi import APIRouter

from app.api.routes.health import router as health_router
from app.api.routes.mvp import router as mvp_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
api_router.include_router(mvp_router, tags=["mvp"])
