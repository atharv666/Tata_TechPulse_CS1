"""Bind staged relationship candidates (endpoint *names*) to canonical entities.

Extraction records what a chunk says (``A REQUIRES B``) without knowing which entities exist. This
runs after entity resolution and turns each candidate into a relationship between canonical
entities, adding the candidate's excerpt as evidence. It looks names up in the *final* entity set,
so the result does not depend on the order chunks were processed in. A candidate it cannot bind
(unknown name, ambiguous name, rejected endpoint) stays ``UNBOUND`` with a note, and surfaces as a
finding; nothing is dropped silently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.knowledge.rules import RELATIONSHIP_RULES
from app.models.enums import ExtractionType, SourceClassification, ValidationState
from app.models.schema import (
    Entity,
    EntityAlias,
    Relationship,
    RelationshipCandidate,
    RelationshipEvidence,
)


@dataclass(frozen=True)
class BindingProblem:
    """A candidate that could not be bound, in a form findings can group and explain."""

    kind: str  # MISSING | AMBIGUOUS | REJECTED | SAME
    candidate: RelationshipCandidate
    side: str  # source | target
    name: str
    normalized: str
    matches: tuple[str, ...] = ()

    @property
    def message(self) -> str:
        if self.kind == "MISSING":
            return f"The {self.side} '{self.name}' is not defined as an entity."
        if self.kind == "REJECTED":
            return f"The {self.side} '{self.name}' was rejected by a reviewer."
        if self.kind == "AMBIGUOUS":
            options = ", ".join(self.matches)
            return f"The {self.side} '{self.name}' matches several entities: {options}."
        return "Both endpoints resolve to the same entity."


@dataclass
class BindingResult:
    problems: list[BindingProblem] = field(default_factory=list)
    candidates: int = 0
    bound: int = 0
    relationships_created: int = 0
    missing_endpoint: int = 0
    ambiguous_endpoint: int = 0
    rejected_endpoint: int = 0
    same_endpoint: int = 0

    @property
    def unbound(self) -> int:
        return self.candidates - self.bound


@dataclass(frozen=True)
class _Lookup:
    state: str  # OK | MISSING | AMBIGUOUS | REJECTED
    entity: Entity | None = None
    matches: tuple[str, ...] = ()


class RelationshipBinder:
    def bind(self, session: Session, project_id: UUID) -> BindingResult:
        result = BindingResult()
        lookup = self._name_index(session, project_id)
        candidates = list(
            session.scalars(
                select(RelationshipCandidate)
                .where(RelationshipCandidate.project_id == project_id)
                .order_by(
                    RelationshipCandidate.relationship_type,
                    RelationshipCandidate.normalized_source,
                    RelationshipCandidate.normalized_target,
                    RelationshipCandidate.chunk_id,
                    RelationshipCandidate.id,
                )
            )
        )
        result.candidates = len(candidates)
        aggregate: dict[UUID, tuple[Decimal, bool]] = {}
        cache: dict[tuple[UUID, UUID, str], Relationship] = {}
        for candidate in candidates:
            source = self._resolve(lookup, candidate.normalized_source, candidate, "sources")
            target = self._resolve(lookup, candidate.normalized_target, candidate, "targets")
            problem = self._problem(source, target, candidate, result)
            if problem is not None or source.entity is None or target.entity is None:
                candidate.status, candidate.relationship_id = "UNBOUND", None
                candidate.note = problem.message if problem is not None else None
                continue
            relationship = self._relationship(
                session, project_id, source.entity, target.entity, candidate, cache, result
            )
            self._evidence(session, project_id, relationship, candidate)
            candidate.status, candidate.relationship_id, candidate.note = (
                "BOUND",
                relationship.id,
                None,
            )
            result.bound += 1
            best, explicit = aggregate.get(relationship.id, (Decimal("0"), False))
            aggregate[relationship.id] = (
                max(best, candidate.confidence),
                explicit or candidate.extraction_type == "EXPLICIT",
            )
        self._apply_aggregates(session, aggregate)
        session.flush()
        return result

    # -- lookup ------------------------------------------------------------------------------
    @staticmethod
    def _name_index(session: Session, project_id: UUID) -> dict[str, list[Entity]]:
        entities = {
            entity.id: entity
            for entity in session.scalars(
                select(Entity).where(
                    Entity.project_id == project_id,
                    Entity.merged_into_id.is_(None),
                    Entity.superseded_by_id.is_(None),
                )
            )
        }
        index: dict[str, list[Entity]] = {}
        for entity in entities.values():
            index.setdefault(entity.normalized_name, []).append(entity)
        for alias in session.scalars(
            select(EntityAlias).where(EntityAlias.project_id == project_id)
        ):
            owner = entities.get(alias.entity_id)
            if owner is not None and owner not in index.get(alias.normalized_alias, []):
                index.setdefault(alias.normalized_alias, []).append(owner)
        return index

    @staticmethod
    def _resolve(
        index: dict[str, list[Entity]],
        normalized: str,
        candidate: RelationshipCandidate,
        side: str,
    ) -> _Lookup:
        found = index.get(normalized, [])
        usable = [entity for entity in found if entity.validation_state != ValidationState.REJECTED]
        if not usable:
            return _Lookup("REJECTED" if found else "MISSING")
        if len(usable) == 1:
            return _Lookup("OK", usable[0])
        rule = RELATIONSHIP_RULES.get(candidate.relationship_type)
        allowed = getattr(rule, side, None) if rule is not None else None
        plausible = [e for e in usable if allowed is None or e.entity_type in allowed]
        if len(plausible) == 1:
            return _Lookup("OK", plausible[0])
        return _Lookup(
            "AMBIGUOUS",
            None,
            tuple(sorted(f"{e.canonical_name} [{e.entity_type}]" for e in usable)),
        )

    @staticmethod
    def _problem(
        source: _Lookup,
        target: _Lookup,
        candidate: RelationshipCandidate,
        result: BindingResult,
    ) -> BindingProblem | None:
        for side, lookup, name, normalized in (
            ("source", source, candidate.source_name, candidate.normalized_source),
            ("target", target, candidate.target_name, candidate.normalized_target),
        ):
            if lookup.state != "OK":
                counter = {
                    "MISSING": "missing_endpoint",
                    "REJECTED": "rejected_endpoint",
                    "AMBIGUOUS": "ambiguous_endpoint",
                }[lookup.state]
                setattr(result, counter, getattr(result, counter) + 1)
                problem = BindingProblem(
                    lookup.state, candidate, side, name, normalized, lookup.matches
                )
                result.problems.append(problem)
                return problem
        if (
            source.entity is not None
            and target.entity is not None
            and source.entity.id == target.entity.id
        ):
            result.same_endpoint += 1
            problem = BindingProblem(
                "SAME", candidate, "source", candidate.source_name, candidate.normalized_source
            )
            result.problems.append(problem)
            return problem
        return None

    # -- relationships and evidence ----------------------------------------------------------
    @staticmethod
    def _relationship(
        session: Session,
        project_id: UUID,
        source: Entity,
        target: Entity,
        candidate: RelationshipCandidate,
        cache: dict[tuple[UUID, UUID, str], Relationship],
        result: BindingResult,
    ) -> Relationship:
        key = (source.id, target.id, candidate.relationship_type)
        relationship = cache.get(key)
        if relationship is None:
            relationship = session.scalars(
                select(Relationship)
                .where(
                    Relationship.project_id == project_id,
                    Relationship.source_entity_id == source.id,
                    Relationship.target_entity_id == target.id,
                    Relationship.relationship_type == candidate.relationship_type,
                )
                # An active relationship wins. A *superseded* one (replaced by a reviewer's
                # correction or merged away) still counts as "this statement was decided":
                # binding to it keeps the AI proposal from being resurrected on every rebuild.
                .order_by(
                    Relationship.superseded_by_id.is_not(None),
                    Relationship.created_at,
                    Relationship.id,
                )
            ).first()
        if relationship is None:
            relationship = Relationship(
                project_id=project_id,
                source_entity_id=source.id,
                target_entity_id=target.id,
                relationship_type=candidate.relationship_type,
                extraction_type=ExtractionType(candidate.extraction_type),
                raw_confidence=candidate.confidence,
                confidence=candidate.confidence,
                attributes={"origin": "extraction"},
            )
            session.add(relationship)
            session.flush()
            result.relationships_created += 1
        cache[key] = relationship
        return relationship

    @staticmethod
    def _evidence(
        session: Session,
        project_id: UUID,
        relationship: Relationship,
        candidate: RelationshipCandidate,
    ) -> None:
        exists = session.scalar(
            select(RelationshipEvidence.id).where(
                RelationshipEvidence.relationship_id == relationship.id,
                RelationshipEvidence.chunk_id == candidate.chunk_id,
            )
        )
        if exists is None:
            session.add(
                RelationshipEvidence(
                    project_id=project_id,
                    relationship_id=relationship.id,
                    chunk_id=candidate.chunk_id,
                    source_classification=SourceClassification(candidate.source_classification),
                    excerpt=candidate.excerpt,
                    start_offset=candidate.start_offset,
                    end_offset=candidate.end_offset,
                )
            )

    @staticmethod
    def _apply_aggregates(session: Session, aggregate: dict[UUID, tuple[Decimal, bool]]) -> None:
        """A pending relationship carries the best claim any of its sources made (order-free)."""
        for relationship_id, (best, explicit) in aggregate.items():
            relationship = session.get(Relationship, relationship_id)
            if relationship is None or relationship.validation_state is not ValidationState.PENDING:
                continue  # reviewed facts keep what the reviewer decided
            relationship.raw_confidence = best
            relationship.extraction_type = (
                ExtractionType.EXPLICIT if explicit else ExtractionType.INFERRED
            )
