"""Infrastructure health endpoint."""

from fastapi import APIRouter, status

from app.core.errors import ApplicationError
from app.db.session import check_database
from app.schemas.health import HealthResponse
from app.services.health import get_health_status

router = APIRouter()


@router.get("/health", response_model=HealthResponse, status_code=status.HTTP_200_OK)
def health_check() -> HealthResponse:
    """Return process health; domain service dependencies are intentionally excluded."""
    return get_health_status()


@router.get("/health/ready", response_model=HealthResponse, status_code=status.HTTP_200_OK)
def readiness_check() -> HealthResponse:
    """Confirm required database extensions without masking dependency failures."""
    try:
        check_database()
    except Exception as error:
        raise ApplicationError(
            "DATABASE_UNAVAILABLE", "Database unavailable.", status.HTTP_503_SERVICE_UNAVAILABLE
        ) from error
    return get_health_status()
