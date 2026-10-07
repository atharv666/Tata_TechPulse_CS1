"""Evidence-preserving, deterministic comparison of architectural document revisions."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import ComparisonState, JobState
from app.models.schema import Comparison, ComparisonFinding, Entity, Job, Relationship
from app.repositories.comparisons import ComparisonRepository
from app.retrieval.evidence import Citation
from app.retrieval.impact import ImpactResult


class ChangeClassification(StrEnum):
    ADDED = "ADDED"
    REMOVED = "REMOVED"
    UNCHANGED = "UNCHANGED"
    RENAMED = "RENAMED"
    TYPE_CHANGED = "TYPE_CHANGED"
    TARGET_CHANGED = "TARGET_CHANGED"
    SOURCE_CHANGED = "SOURCE_CHANGED"
    RELATIONSHIP_TYPE_CHANGED = "RELATIONSHIP_TYPE_CHANGED"
    CONFIDENCE_CHANGED = "CONFIDENCE_CHANGED"
    STATUS_CHANGED = "STATUS_CHANGED"


class ChangeSeverity(StrEnum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class RevisionEvidence(BaseModel):
    citations: list[Citation] = Field(default_factory=list)


class RevisionFinding(BaseModel):
    classification: ChangeClassification
    severity: ChangeSeverity
    entity_id: UUID | None = None
    old_fact_id: UUID | None = None
    new_fact_id: UUID | None = None
    summary: str
    old_evidence: RevisionEvidence
    new_evidence: RevisionEvidence
    review_status: str
    potential_conflict: bool = False
    impacts: list[ImpactResult] = Field(default_factory=list)


class RevisionComparisonResult(BaseModel):
    base_version_id: UUID
    target_version_id: UUID
    findings: list[RevisionFinding]


@dataclass(frozen=True)
class RevisionSnapshot:
    version_id: UUID
    entities: list[Entity]
    relationships: list[Relationship]
    entity_evidence: dict[UUID, RevisionEvidence]
    relationship_evidence: dict[UUID, RevisionEvidence]


class RevisionComparisonService:
    """Compares version-evidenced graph snapshots without treating differences as contradictions."""

    def compare(
        self,
        project_id: UUID,
        base: RevisionSnapshot,
        target: RevisionSnapshot,
        impacts: dict[UUID, list[ImpactResult]] | None = None,
    ) -> RevisionComparisonResult:
        if base.version_id == target.version_id:
            raise ValueError("Comparison requires two distinct document versions.")
        base_entities = self._entities_for(project_id, base)
        target_entities = self._entities_for(project_id, target)
        findings = self._entity_findings(
            base_entities, target_entities, base, target, impacts or {}
        )
        findings.extend(self._relationship_findings(project_id, base, target, impacts or {}))
        return RevisionComparisonResult(
            base_version_id=base.version_id, target_version_id=target.version_id, findings=findings
        )

    @staticmethod
    def _entities_for(project_id: UUID, snapshot: RevisionSnapshot) -> list[Entity]:
        return [
            entity
            for entity in snapshot.entities
            if entity.project_id == project_id
            and any(
                c.document_version_id == snapshot.version_id
                for c in snapshot.entity_evidence.get(entity.id, RevisionEvidence()).citations
            )
        ]

    def _entity_findings(
        self,
        base_entities: list[Entity],
        target_entities: list[Entity],
        base: RevisionSnapshot,
        target: RevisionSnapshot,
        impacts: dict[UUID, list[ImpactResult]],
    ) -> list[RevisionFinding]:
        findings: list[RevisionFinding] = []
        old_by_name = {entity.normalized_name: entity for entity in base_entities}
        new_by_name = {entity.normalized_name: entity for entity in target_entities}
        matched_old: set[UUID] = set()
        matched_new: set[UUID] = set()
        for name in old_by_name.keys() & new_by_name.keys():
            old, new = old_by_name[name], new_by_name[name]
            matched_old.add(old.id)
            matched_new.add(new.id)
            classification = self._same_name_change(old, new)
            findings.append(self._entity_finding(classification, old, new, base, target, impacts))
        old_remaining = [entity for entity in base_entities if entity.id not in matched_old]
        new_remaining = [entity for entity in target_entities if entity.id not in matched_new]
        for old in tuple(old_remaining):
            rename = self._rename_candidate(old, new_remaining)
            if rename is not None:
                new_remaining.remove(rename)
                old_remaining.remove(old)
                findings.append(
                    self._entity_finding(
                        ChangeClassification.RENAMED, old, rename, base, target, impacts
                    )
                )
        for old in old_remaining:
            findings.append(
                self._entity_finding(ChangeClassification.REMOVED, old, None, base, target, impacts)
            )
        for new in new_remaining:
            findings.append(
                self._entity_finding(ChangeClassification.ADDED, None, new, base, target, impacts)
            )
        return findings

    @staticmethod
    def _same_name_change(old: Entity, new: Entity) -> ChangeClassification:
        if old.entity_type != new.entity_type:
            return ChangeClassification.TYPE_CHANGED
        if old.validation_state != new.validation_state:
            return ChangeClassification.STATUS_CHANGED
        if old.confidence != new.confidence:
            return ChangeClassification.CONFIDENCE_CHANGED
        return ChangeClassification.UNCHANGED

    @staticmethod
    def _rename_candidate(old: Entity, candidates: list[Entity]) -> Entity | None:
        same_type = [
            candidate for candidate in candidates if candidate.entity_type == old.entity_type
        ]
        scored = [
            (
                SequenceMatcher(None, old.normalized_name, candidate.normalized_name).ratio(),
                candidate,
            )
            for candidate in same_type
        ]
        if not scored:
            return None
        score, candidate = max(scored, key=lambda value: value[0])
        return candidate if score >= 0.80 else None

    def _entity_finding(
        self,
        classification: ChangeClassification,
        old: Entity | None,
        new: Entity | None,
        base: RevisionSnapshot,
        target: RevisionSnapshot,
        impacts: dict[UUID, list[ImpactResult]],
    ) -> RevisionFinding:
        fact = new or old
        assert fact is not None
        old_evidence = (
            base.entity_evidence.get(old.id, RevisionEvidence()) if old else RevisionEvidence()
        )
        new_evidence = (
            target.entity_evidence.get(new.id, RevisionEvidence()) if new else RevisionEvidence()
        )
        if old is not None:
            label = old.canonical_name
        else:
            assert new is not None
            label = new.canonical_name
        return RevisionFinding(
            classification=classification,
            severity=self._severity(classification),
            entity_id=fact.id,
            old_fact_id=old.id if old else None,
            new_fact_id=new.id if new else None,
            summary=f"Entity {classification}: {label}",
            old_evidence=old_evidence,
            new_evidence=new_evidence,
            review_status=fact.validation_state.value,
            impacts=impacts.get(fact.id, []),
        )

    def _relationship_findings(
        self,
        project_id: UUID,
        base: RevisionSnapshot,
        target: RevisionSnapshot,
        impacts: dict[UUID, list[ImpactResult]],
    ) -> list[RevisionFinding]:
        old = self._relationships_for(project_id, base)
        new = self._relationships_for(project_id, target)
        old_by_source_type = {(item.source_entity_id, item.relationship_type): item for item in old}
        new_by_source_type = {(item.source_entity_id, item.relationship_type): item for item in new}
        findings: list[RevisionFinding] = []
        for key in old_by_source_type.keys() & new_by_source_type.keys():
            before, after = old_by_source_type[key], new_by_source_type[key]
            if before.target_entity_id != after.target_entity_id:
                findings.append(
                    self._relationship_finding(
                        ChangeClassification.TARGET_CHANGED, before, after, base, target, impacts
                    )
                )
        old_by_target_type = {(item.target_entity_id, item.relationship_type): item for item in old}
        new_by_target_type = {(item.target_entity_id, item.relationship_type): item for item in new}
        for key in old_by_target_type.keys() & new_by_target_type.keys():
            before, after = old_by_target_type[key], new_by_target_type[key]
            if before.source_entity_id != after.source_entity_id:
                findings.append(
                    self._relationship_finding(
                        ChangeClassification.SOURCE_CHANGED, before, after, base, target, impacts
                    )
                )
        old_by_endpoints = {(item.source_entity_id, item.target_entity_id): item for item in old}
        new_by_endpoints = {(item.source_entity_id, item.target_entity_id): item for item in new}
        shared_endpoints = set(old_by_endpoints).intersection(new_by_endpoints)
        for endpoint_key in shared_endpoints:
            before, after = old_by_endpoints[endpoint_key], new_by_endpoints[endpoint_key]
            if before.relationship_type != after.relationship_type:
                findings.append(
                    self._relationship_finding(
                        ChangeClassification.RELATIONSHIP_TYPE_CHANGED,
                        before,
                        after,
                        base,
                        target,
                        impacts,
                    )
                )
        return findings

    @staticmethod
    def _relationships_for(project_id: UUID, snapshot: RevisionSnapshot) -> list[Relationship]:
        return [
            relationship
            for relationship in snapshot.relationships
            if relationship.project_id == project_id
            and any(
                c.document_version_id == snapshot.version_id
                for c in snapshot.relationship_evidence.get(
                    relationship.id, RevisionEvidence()
                ).citations
            )
        ]

    def _relationship_finding(
        self,
        classification: ChangeClassification,
        old: Relationship,
        new: Relationship,
        base: RevisionSnapshot,
        target: RevisionSnapshot,
        impacts: dict[UUID, list[ImpactResult]],
    ) -> RevisionFinding:
        return RevisionFinding(
            classification=classification,
            severity=self._severity(classification),
            old_fact_id=old.id,
            new_fact_id=new.id,
            summary=f"Relationship {classification}: {old.relationship_type}",
            old_evidence=base.relationship_evidence.get(old.id, RevisionEvidence()),
            new_evidence=target.relationship_evidence.get(new.id, RevisionEvidence()),
            review_status=new.validation_state.value,
            impacts=impacts.get(new.source_entity_id, []),
        )

    @staticmethod
    def _severity(classification: ChangeClassification) -> ChangeSeverity:
        if classification in {
            ChangeClassification.REMOVED,
            ChangeClassification.TARGET_CHANGED,
            ChangeClassification.SOURCE_CHANGED,
        }:
            return ChangeSeverity.HIGH
        if classification in {
            ChangeClassification.TYPE_CHANGED,
            ChangeClassification.RELATIONSHIP_TYPE_CHANGED,
        }:
            return ChangeSeverity.MEDIUM
        return ChangeSeverity.INFO


class ComparisonJobService:
    """Persists explicit comparison jobs and finding snapshots without changing source facts."""

    def __init__(self, comparer: RevisionComparisonService | None = None) -> None:
        self._comparer = comparer or RevisionComparisonService()

    def run(
        self,
        repository: ComparisonRepository,
        actor_id: str,
        base: RevisionSnapshot,
        target: RevisionSnapshot,
        impacts: dict[UUID, list[ImpactResult]] | None = None,
    ) -> tuple[Comparison, Job, RevisionComparisonResult]:
        repository.require_version(base.version_id)
        repository.require_version(target.version_id)
        comparison = Comparison(
            project_id=repository.project_id,
            base_version_id=base.version_id,
            target_version_id=target.version_id,
            requested_by=actor_id,
            state=ComparisonState.PENDING,
        )
        job = Job(
            project_id=repository.project_id,
            job_type="REVISION_COMPARISON",
            state=JobState.RUNNING,
            requested_by=actor_id,
            details={},
        )
        repository.add_comparison(comparison)
        repository.add_job(job)
        repository.session.flush()
        result = self._comparer.compare(repository.project_id, base, target, impacts)
        for finding in result.findings:
            repository.add_finding(
                ComparisonFinding(
                    project_id=repository.project_id,
                    comparison_id=comparison.id,
                    entity_id=finding.entity_id,
                    finding_type=finding.classification.value,
                    confidence=0,
                    summary=finding.summary,
                    details=finding.model_dump(mode="json"),
                )
            )
        comparison.state = ComparisonState.COMPLETED
        job.state = JobState.COMPLETED
        job.details = {"comparison_id": str(comparison.id), "findings": len(result.findings)}
        return comparison, job, result
