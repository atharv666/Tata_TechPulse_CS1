"""Applying and undoing an entity merge.

A merge is *soft*: the merged entity row stays (``merged_into_id`` points at the survivor), so the
original AI extraction and its evidence trail are never destroyed, and everything that moved is
recorded in ``EntityMerge.moved`` so a reviewer can undo it from the admin view.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.canonicalization.view import pair_key
from app.models.schema import (
    Entity,
    EntityAlias,
    EntityEvidence,
    EntityMerge,
    MergeDecision,
    Relationship,
    RelationshipEvidence,
)

_RANK = {"HUMAN_VERIFIED": 3, "HUMAN_CORRECTED": 3, "REJECTED": 2, "PENDING": 1}


def _rank(relationship: Relationship) -> int:
    return _RANK.get(relationship.validation_state.value, 0)


def apply_merge(
    session: Session,
    survivor: Entity,
    merged: Entity,
    *,
    decided_by: str,
    actor_id: str,
    rule: str | None = None,
    similarity: float | None = None,
    blocking_keys: list[str] | None = None,
    llm_model: str | None = None,
    prompt_version: str | None = None,
    reason: str | None = None,
) -> EntityMerge:
    """Merge ``merged`` into ``survivor`` inside the caller's transaction."""
    if survivor.id == merged.id or survivor.project_id != merged.project_id:
        raise ValueError("A merge needs two different entities of the same project.")
    if merged.merged_into_id is not None or survivor.merged_into_id is not None:
        raise ValueError("Both entities must be active to be merged.")
    moved: dict[str, Any] = {
        "evidence": [],
        "aliases": [],
        "created_aliases": [],
        "relationships": [],
        "superseded": [],
        "relationship_evidence": [],
        "collapsed": [],
    }
    _move_entity_evidence(session, survivor, merged, moved)
    _move_aliases(session, survivor, merged, moved)
    _repoint_relationships(session, survivor, merged, moved)
    merged.merged_into_id = survivor.id
    record = EntityMerge(
        project_id=survivor.project_id,
        canonical_entity_id=survivor.id,
        merged_entity_id=merged.id,
        decided_by=decided_by,
        rule=rule,
        similarity=Decimal(str(round(similarity, 3))) if similarity is not None else None,
        blocking_keys=sorted(blocking_keys or []),
        llm_model=llm_model,
        prompt_version=prompt_version,
        reason=reason,
        moved=moved,
        actor_id=actor_id,
    )
    session.add(record)
    session.flush()
    return record


def _move_entity_evidence(
    session: Session, survivor: Entity, merged: Entity, moved: dict[str, Any]
) -> None:
    known = set(
        session.scalars(
            select(EntityEvidence.chunk_id).where(EntityEvidence.entity_id == survivor.id)
        )
    )
    rows = session.scalars(
        select(EntityEvidence)
        .where(EntityEvidence.entity_id == merged.id)
        .order_by(EntityEvidence.created_at, EntityEvidence.id)
    )
    for row in rows:
        if row.chunk_id in known:
            continue  # the survivor already cites this chunk; this row stays with the merged entity
        row.entity_id = survivor.id
        known.add(row.chunk_id)
        moved["evidence"].append(str(row.id))


def _move_aliases(
    session: Session, survivor: Entity, merged: Entity, moved: dict[str, Any]
) -> None:
    for alias in session.scalars(select(EntityAlias).where(EntityAlias.entity_id == merged.id)):
        alias.entity_id = survivor.id
        moved["aliases"].append(str(alias.id))
    taken = session.scalar(
        select(EntityAlias.id).where(
            EntityAlias.project_id == survivor.project_id,
            EntityAlias.normalized_alias == merged.normalized_name,
        )
    )
    if merged.normalized_name != survivor.normalized_name and taken is None:
        alias = EntityAlias(
            project_id=survivor.project_id,
            entity_id=survivor.id,
            alias=merged.canonical_name,
            normalized_alias=merged.normalized_name,
            source="MERGE",
        )
        session.add(alias)
        moved["created_aliases"].append(str(alias.id))


def _repoint_relationships(
    session: Session, survivor: Entity, merged: Entity, moved: dict[str, Any]
) -> None:
    touching = session.scalars(
        select(Relationship)
        .where(
            Relationship.project_id == survivor.project_id,
            Relationship.superseded_by_id.is_(None),
            (Relationship.source_entity_id == merged.id)
            | (Relationship.target_entity_id == merged.id),
        )
        .order_by(Relationship.created_at, Relationship.id)
    )
    for relationship in list(touching):
        source = (
            survivor.id
            if relationship.source_entity_id == merged.id
            else relationship.source_entity_id
        )
        target = (
            survivor.id
            if relationship.target_entity_id == merged.id
            else relationship.target_entity_id
        )
        if source == target:
            # Between two entities that are now one: it cannot exist as an edge. It stays on the
            # inactive entity, flagged, so the statement is not lost.
            relationship.attributes = {
                **relationship.attributes,
                "inactive_reason": "endpoints merged",
            }
            moved["collapsed"].append(str(relationship.id))
            continue
        twin = session.scalar(
            select(Relationship).where(
                Relationship.project_id == survivor.project_id,
                Relationship.source_entity_id == source,
                Relationship.target_entity_id == target,
                Relationship.relationship_type == relationship.relationship_type,
                Relationship.superseded_by_id.is_(None),
                Relationship.id != relationship.id,
            )
        )
        if twin is None:
            _record_repoint(relationship, source, target, moved)
            continue
        winner, loser = (
            (relationship, twin) if _rank(relationship) > _rank(twin) else (twin, relationship)
        )
        loser.superseded_by_id = winner.id
        moved["superseded"].append(str(loser.id))
        _move_relationship_evidence(session, loser, winner, moved)
        if winner is relationship:
            _record_repoint(relationship, source, target, moved)


def _record_repoint(
    relationship: Relationship, source: UUID, target: UUID, moved: dict[str, Any]
) -> None:
    moved["relationships"].append(
        {
            "id": str(relationship.id),
            "source": str(relationship.source_entity_id),
            "target": str(relationship.target_entity_id),
        }
    )
    relationship.source_entity_id = source
    relationship.target_entity_id = target


def _move_relationship_evidence(
    session: Session, loser: Relationship, winner: Relationship, moved: dict[str, Any]
) -> None:
    known = set(
        session.scalars(
            select(RelationshipEvidence.chunk_id).where(
                RelationshipEvidence.relationship_id == winner.id
            )
        )
    )
    for row in session.scalars(
        select(RelationshipEvidence).where(RelationshipEvidence.relationship_id == loser.id)
    ):
        if row.chunk_id in known:
            continue
        moved["relationship_evidence"].append({"id": str(row.id), "from": str(loser.id)})
        row.relationship_id = winner.id
        known.add(row.chunk_id)


def undo_merge(session: Session, merge: EntityMerge, actor_id: str, reason: str) -> EntityMerge:
    """Reverse a merge and remember that a human said the two entities are different."""
    if merge.undone_at is not None:
        raise ValueError("This merge was already undone.")
    survivor = session.get(Entity, merge.canonical_entity_id)
    merged = session.get(Entity, merge.merged_entity_id)
    if survivor is None or merged is None or merged.merged_into_id != survivor.id:
        raise ValueError("The merged entity is no longer merged into this entity.")
    if survivor.merged_into_id is not None:
        raise ValueError("The surviving entity was merged again; undo that merge first.")
    moved = merge.moved
    for item in moved.get("relationships", []):
        relationship = session.get(Relationship, UUID(item["id"]))
        if relationship is not None:
            relationship.source_entity_id = UUID(item["source"])
            relationship.target_entity_id = UUID(item["target"])
    for item in moved.get("relationship_evidence", []):
        row = session.get(RelationshipEvidence, UUID(item["id"]))
        if row is not None:
            row.relationship_id = UUID(item["from"])
    for relationship_id in moved.get("superseded", []):
        relationship = session.get(Relationship, UUID(relationship_id))
        if relationship is not None:
            relationship.superseded_by_id = None
    for relationship_id in moved.get("collapsed", []):
        relationship = session.get(Relationship, UUID(relationship_id))
        if relationship is not None:
            attributes = dict(relationship.attributes)
            attributes.pop("inactive_reason", None)
            relationship.attributes = attributes
    for evidence_id in moved.get("evidence", []):
        evidence = session.get(EntityEvidence, UUID(evidence_id))
        if evidence is not None:
            evidence.entity_id = merged.id
    for alias_id in moved.get("aliases", []):
        alias = session.get(EntityAlias, UUID(alias_id))
        if alias is not None:
            alias.entity_id = merged.id
    for alias_id in moved.get("created_aliases", []):
        alias = session.get(EntityAlias, UUID(alias_id))
        if alias is not None:
            session.delete(alias)
    merged.merged_into_id = None
    merge.undone_at = datetime.now(UTC)
    merge.undone_by = actor_id
    remember_different(session, survivor, merged, reason or "Merge undone by a reviewer.")
    session.flush()
    return merge


def remember_different(session: Session, first: Entity, second: Entity, reason: str) -> None:
    """Record a human decision that two entities differ; resolution must never merge them."""
    key = pair_key(first.id, second.id)
    decision = session.scalar(
        select(MergeDecision).where(
            MergeDecision.project_id == first.project_id, MergeDecision.pair_key == key
        )
    )
    if decision is None:
        decision = MergeDecision(
            project_id=first.project_id,
            pair_key=key,
            entity_a_id=first.id,
            entity_b_id=second.id,
            decision="DIFFERENT",
            source="HUMAN",
            reason=reason,
            fingerprint="human",
        )
        session.add(decision)
    else:
        decision.decision, decision.source, decision.reason = "DIFFERENT", "HUMAN", reason
        decision.fingerprint = "human"
