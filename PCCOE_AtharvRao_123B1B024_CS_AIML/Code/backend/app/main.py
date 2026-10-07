"""FastAPI application entry point for the AUTOSAR Architecture Intelligence Assistant."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.errors import install_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.metrics import metrics


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Configure process-wide foundations without starting domain pipelines."""
    settings: Settings = get_settings()
    configure_logging(settings.log_level)
    get_logger(__name__).info("application_started", extra={"environment": settings.app_env})
    yield
    get_logger(__name__).info("application_stopped", extra={"environment": settings.app_env})


def create_application() -> FastAPI:
    """Create the HTTP application without coupling routes to domain services."""
    settings: Settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )
    install_exception_handlers(application)

    @application.middleware("http")
    async def add_request_id(request: Request, call_next: object) -> object:
        request.state.request_id = request.headers.get("X-Request-Id", str(uuid4()))
        started = perf_counter()
        response = await call_next(request)  # type: ignore[operator]
        metrics.observe_ms("http_request_latency_ms", (perf_counter() - started) * 1000)
        metrics.increment(f"http_status_{response.status_code}")
        response.headers["X-Request-Id"] = request.state.request_id
        return response

    from fastapi.middleware.cors import CORSMiddleware

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(api_router, prefix=settings.api_v1_prefix)
    return application


app = create_application()
