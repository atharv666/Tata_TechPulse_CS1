"""Health endpoint response schema."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Process-level health state."""

    status: Literal["ok"]
    service: str
    environment: str
    timestamp: datetime
