"""Structured application errors and FastAPI exception handling."""

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.logging import get_logger
from app.core.metrics import metrics
from app.providers.contracts import ProviderError


class ErrorResponse(BaseModel):
    """Stable error envelope for all public API failures."""

    code: str
    message: str
    details: list[dict[str, Any]] | None = None
    request_id: str | None = None


class ApplicationError(Exception):
    """Expected application failure that can be safely reported to a caller."""

    def __init__(
        self, code: str, message: str, status_code: int = status.HTTP_400_BAD_REQUEST
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def install_exception_handlers(application: FastAPI) -> None:
    """Install centralized handlers, keeping endpoint modules free of error plumbing."""

    @application.exception_handler(ApplicationError)
    async def application_error_handler(request: Request, error: ApplicationError) -> JSONResponse:
        metrics.increment(f"error_category_{error.code}")
        return JSONResponse(
            status_code=error.status_code,
            content=ErrorResponse(
                code=error.code,
                message=error.message,
                request_id=getattr(request.state, "request_id", None),
            ).model_dump(),
        )

    @application.exception_handler(RequestValidationError)
    async def request_validation_handler(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        metrics.increment("error_category_REQUEST_VALIDATION_ERROR")
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=ErrorResponse(
                code="REQUEST_VALIDATION_ERROR",
                message="The request payload is invalid.",
                details=[dict(item) for item in error.errors()],
                request_id=getattr(request.state, "request_id", None),
            ).model_dump(),
        )

    @application.exception_handler(PermissionError)
    async def permission_error_handler(request: Request, error: PermissionError) -> JSONResponse:
        metrics.increment("error_category_AUTHORIZATION_FAILED")
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content=ErrorResponse(
                code="AUTHORIZATION_FAILED",
                message=str(error),
                request_id=getattr(request.state, "request_id", None),
            ).model_dump(),
        )

    @application.exception_handler(ValueError)
    async def value_error_handler(request: Request, error: ValueError) -> JSONResponse:
        metrics.increment("error_category_DOMAIN_VALIDATION_ERROR")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=ErrorResponse(
                code="DOMAIN_VALIDATION_ERROR",
                message=str(error),
                request_id=getattr(request.state, "request_id", None),
            ).model_dump(),
        )

    @application.exception_handler(ProviderError)
    async def provider_error_handler(request: Request, error: ProviderError) -> JSONResponse:
        metrics.increment("error_category_PROVIDER_UNAVAILABLE")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=ErrorResponse(
                code="PROVIDER_UNAVAILABLE",
                message=str(error),
                request_id=getattr(request.state, "request_id", None),
            ).model_dump(),
        )

    @application.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, error: Exception) -> JSONResponse:
        metrics.increment("error_category_INTERNAL_ERROR")
        get_logger(__name__).exception("unexpected_error", exc_info=error)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=ErrorResponse(
                code="INTERNAL_ERROR",
                message="An unexpected error occurred.",
                request_id=getattr(request.state, "request_id", None),
            ).model_dump(),
        )
