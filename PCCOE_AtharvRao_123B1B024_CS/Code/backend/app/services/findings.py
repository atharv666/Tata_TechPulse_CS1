"""Persistence and review operations for architecture findings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.models.schema import AuditEvent, Finding
from app.validation.findings import GRAPH_FINDING_TYPES, FindingDraft

OPEN, DISMISSED, RESOLVED = "OPEN", "DISMISSED", "RESOLVED"


class FindingNotFoundError(NotFoundError):
    """The finding does not exist in the requested project."""

    def __init__(self, finding_id: object) -> None:
        super().__init__("FINDING_NOT_FOUND", f"Finding {finding_id} was not found.")


class FindingStateError(ConflictError):
    """The requested transition is not valid for the finding's current state."""

    def __init__(self, message: str) -> None:
        super().__init__("FINDING_STATE_CONFLICT", message)


@dataclass(frozen=True)
class SyncResult:
    opened: int = 0
    reopened: int = 0
    resolved: int = 0
    open_total: int = 0


def sync_findings(
    session: Session,
    project_id: UUID,
    drafts: list[FindingDraft],
    managed_types: tuple[str, ...] = GRAPH_FINDING_TYPES,
) -> SyncResult:
    """Make the stored findings match what detection currently reports, idempotently.

    * new situation -> OPEN;
    * a situation that was resolved and is detected again -> reopened;
    * a situation a reviewer dismissed stays dismissed (its details are refreshed);
    * an OPEN finding that is no longer detected -> RESOLVED automatically.
    """
    existing = {
        row.fingerprint: row
        for row in session.scalars(
            select(Finding).where(
                Finding.project_id == project_id, Finding.finding_type.in_(managed_types)
            )
        )
    }
    opened = reopened = 0
    seen: set[str] = set()
    for draft in drafts:
        seen.add(draft.fingerprint)
        row = existing.get(draft.fingerprint)
        if row is None:
            row = Finding(
                project_id=project_id,
                finding_type=draft.finding_type,
                fingerprint=draft.fingerprint,
                status=OPEN,
            )
            session.add(row)
            opened += 1
        elif row.status == RESOLVED:
            row.status, row.resolved_at = OPEN, None
            reopened += 1
        row.severity = draft.severity
        row.summary = draft.summary
        row.details = draft.details
        row.entity_id = draft.entity_id
        row.relationship_id = draft.relationship_id
        row.confidence = draft.confidence
    resolved = 0
    now = datetime.now(UTC)
    for fingerprint, row in existing.items():
        if fingerprint not in seen and row.status == OPEN:
            row.status, row.resolved_at = RESOLVED, now
            resolved += 1
    session.flush()
    open_total = int(
        session.scalar(
            select(func.count(Finding.id)).where(
                Finding.project_id == project_id,
                Finding.status == OPEN,
                Finding.finding_type.in_(managed_types),
            )
        )
        or 0
    )
    return SyncResult(opened, reopened, resolved, open_total)


class FindingsService:
    """Project-scoped listing and reviewer actions."""

    def __init__(self, session: Session, project_id: UUID, actor_id: str) -> None:
        self._session = session
        self._project_id = project_id
        self._actor_id = actor_id

    def list(
        self,
        *,
        status: str | None = None,
        finding_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Finding], int]:
        conditions = [Finding.project_id == self._project_id]
        if status:
            conditions.append(Finding.status == status)
        if finding_type:
            conditions.append(Finding.finding_type == finding_type)
        total = int(self._session.scalar(select(func.count(Finding.id)).where(*conditions)) or 0)
        severity_order = case({"HIGH": 0, "MEDIUM": 1, "LOW": 2}, value=Finding.severity, else_=3)
        rows = self._session.scalars(
            select(Finding)
            .where(*conditions)
            .order_by(severity_order, Finding.created_at, Finding.id)
            .limit(limit)
            .offset(offset)
        )
        return list(rows), total

    def get(self, finding_id: UUID) -> Finding:
        row = self._session.scalar(
            select(Finding).where(Finding.project_id == self._project_id, Finding.id == finding_id)
        )
        if row is None:
            raise FindingNotFoundError(finding_id)
        return row

    def dismiss(self, finding_id: UUID, reason: str) -> Finding:
        row = self.get(finding_id)
        if not reason.strip():
            raise ValueError("A reason is required to dismiss a finding.")
        if row.status == DISMISSED:
            return row
        row.status = DISMISSED
        row.dismissed_by, row.dismissed_reason = self._actor_id, reason.strip()
        row.dismissed_at = datetime.now(UTC)
        self._audit("FINDING_DISMISSED", row, {"reason": reason.strip()})
        self._session.flush()
        return row

    def reopen(self, finding_id: UUID) -> Finding:
        row = self.get(finding_id)
        if row.status != DISMISSED:
            raise FindingStateError("Only a dismissed finding can be reopened.")
        row.status = OPEN
        row.dismissed_by = row.dismissed_reason = row.dismissed_at = None
        self._audit("FINDING_REOPENED", row, {})
        self._session.flush()
        return row

    def _audit(self, action: str, row: Finding, details: dict[str, object]) -> None:
        self._session.add(
            AuditEvent(
                project_id=self._project_id,
                actor_id=self._actor_id,
                action=action,
                resource_type="finding",
                resource_id=row.id,
                details={"finding_type": row.finding_type, **details},
            )
        )
