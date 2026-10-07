"""Project and membership aggregate persistence."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.schema import Project, ProjectMember


class ProjectRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, project: Project) -> Project:
        self.session.add(project)
        return project

    def get(self, project_id: UUID) -> Project | None:
        return self.session.get(Project, project_id)

    def add_member(self, member: ProjectMember) -> ProjectMember:
        self.session.add(member)
        return member

    def member_for(self, project_id: UUID, user_id: str) -> ProjectMember | None:
        return self.session.scalar(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id, ProjectMember.user_id == user_id
            )
        )
