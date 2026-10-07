"""Audit event service for meaningful, project-scoped state changes."""

from uuid import UUID

from app.models.schema import AuditEvent
from app.repositories.review import ReviewRepository
from app.schemas.review import AuditEventDisplay


class AuditEventService:
    """Writes immutable audit events without modifying the reviewed resource."""

    def __init__(self, repository: ReviewRepository, actor_id: str) -> None:
        self._repository = repository
        self._actor_id = actor_id

    def record(
        self,
        action: str,
        resource_type: str,
        resource_id: UUID,
        details: dict[str, object],
    ) -> AuditEvent:
        event = AuditEvent(
            project_id=self._repository.project_id,
            actor_id=self._actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
        )
        return self._repository.record_audit(event)

    def history(self, resource_id: UUID | None = None) -> list[AuditEventDisplay]:
        return [
            AuditEventDisplay(
                action=event.action,
                resource_type=event.resource_type,
                resource_id=event.resource_id,
                actor_id=event.actor_id,
                details=event.details,
                created_at=event.created_at,
            )
            for event in self._repository.audit_history(resource_id)
        ]
