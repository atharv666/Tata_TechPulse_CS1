"""Which document versions may ground an answer, and what status each one declares."""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.schema import DocumentVersion


def version_statuses(session: Session, version_ids: Iterable[UUID]) -> dict[UUID, str | None]:
    """The status each version's own header declares (``None`` when it declares none)."""
    ids = set(version_ids)
    if not ids:
        return {}
    rows = session.execute(
        select(DocumentVersion.id, DocumentVersion.properties).where(DocumentVersion.id.in_(ids))
    )
    return {
        version_id: (str(properties.get("status")) if properties.get("status") else None)
        for version_id, properties in rows
    }


def approved_version_ids(session: Session, project_id: UUID, statuses: list[str]) -> list[UUID]:
    """Versions of the project whose declared status is one of ``statuses`` (case-insensitive)."""
    wanted = {item.strip().casefold() for item in statuses}
    rows = session.execute(
        select(DocumentVersion.id, DocumentVersion.properties).where(
            DocumentVersion.project_id == project_id
        )
    )
    return [
        version_id
        for version_id, properties in rows
        if str(properties.get("status") or "").strip().casefold() in wanted
    ]
