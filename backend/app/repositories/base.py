"""Project-scoped repository helpers."""

from typing import TypeVar
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models.base import Base

ModelType = TypeVar("ModelType", bound=Base)


class ProjectScopedRepository:
    """Base class that requires a project identifier for every aggregate operation."""

    def __init__(self, session: Session, project_id: UUID) -> None:
        self.session = session
        self.project_id = project_id

    def within_project(self, model: type[ModelType]) -> Select[tuple[ModelType]]:
        """Build a query constrained to the repository's project boundary."""
        return select(model).where(model.project_id == self.project_id)  # type: ignore[attr-defined]
