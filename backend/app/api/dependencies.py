"""HTTP dependencies for development identity, project authorization, and request IDs."""

from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ApplicationError
from app.db.session import get_db_session
from app.models.enums import MembershipRole
from app.repositories.projects import ProjectRepository


@dataclass(frozen=True)
class CurrentUser:
    user_id: str


@dataclass(frozen=True)
class ProjectAccess:
    project_id: UUID
    user_id: str
    role: MembershipRole


def get_current_user(x_user_id: str | None = Header(default=None)) -> CurrentUser:
    if get_settings().auth_mode != "development":
        raise ApplicationError(
            "AUTH_PROVIDER_REQUIRED", "Enterprise authentication must be configured.", 503
        )
    if x_user_id is None or not x_user_id.strip():
        raise ApplicationError("AUTHENTICATION_REQUIRED", "X-User-Id is required.", 401)
    return CurrentUser(x_user_id)


def project_access(
    project_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> ProjectAccess:
    member = ProjectRepository(session).member_for(project_id, user.user_id)
    if member is None:
        raise ApplicationError("PROJECT_ACCESS_DENIED", "Project access is denied.", 403)
    return ProjectAccess(project_id, user.user_id, member.role)
