"""Revision comparison tests: changes retain both version evidence and stay non-contradictory."""

from decimal import Decimal
from uuid import UUID, uuid4

from app.models.enums import ExtractionType, TrustState, ValidationState
from app.models.schema import Entity, Relationship
from app.retrieval.evidence import Citation
from app.retrieval.revision import (
    ChangeClassification,
    RevisionComparisonService,
    RevisionEvidence,
    RevisionSnapshot,
)


def entity(
    project_id: UUID, name: str, kind: str = "COMPONENT", entity_id: UUID | None = None
) -> Entity:
    return Entity(
        id=entity_id or uuid4(),
        project_id=project_id,
        canonical_name=name,
        normalized_name=name.casefold(),
        entity_type=kind,
        trust_state=TrustState.CANDIDATE,
        extraction_type=ExtractionType.EXPLICIT,
        validation_state=ValidationState.PENDING,
        confidence=Decimal("0.800"),
        extraction_metadata={},
    )


def relationship(
    project_id: UUID, source: Entity, target: Entity, kind: str
) -> Relationship:
    return Relationship(
        id=uuid4(),
        project_id=project_id,
        source_entity_id=source.id,
        target_entity_id=target.id,
        relationship_type=kind,
        trust_state=TrustState.CANDIDATE,
        extraction_type=ExtractionType.EXPLICIT,
        validation_state=ValidationState.PENDING,
        confidence=Decimal("0.800"),
        attributes={},
    )


def evidence(version: UUID, text: str) -> RevisionEvidence:
    chunk_id = uuid4()
    return RevisionEvidence(
        citations=[
            Citation(
                citation_id=f"chunk:{chunk_id}",
                chunk_id=chunk_id,
                document_id=uuid4(),
                document_version_id=version,
                document_name="HLD",
                section_heading="Architecture",
                page_start=1,
                page_end=1,
                excerpt=text,
            )
        ]
    )


def snapshot(
    version: UUID,
    entities: list[Entity],
    relationships: list[Relationship] | None = None,
    entity_evidence: dict[UUID, RevisionEvidence] | None = None,
    relationship_evidence: dict[UUID, RevisionEvidence] | None = None,
) -> RevisionSnapshot:
    return RevisionSnapshot(
        version,
        entities,
        relationships or [],
        entity_evidence
        or {item.id: evidence(version, item.canonical_name) for item in entities},
        relationship_evidence or {},
    )


def test_entity_added_removed_and_evidence_mapping_are_preserved() -> None:
    project, old_version, new_version = uuid4(), uuid4(), uuid4()
    removed = entity(project, "OldComponent")
    added = entity(project, "NewComponent")
    base = snapshot(old_version, [removed])
    target = snapshot(new_version, [added])

    result = RevisionComparisonService().compare(project, base, target)
    classifications = {finding.classification for finding in result.findings}

    assert {ChangeClassification.REMOVED, ChangeClassification.ADDED} <= classifications
    removed_finding = next(
        finding
        for finding in result.findings
        if finding.classification is ChangeClassification.REMOVED
    )
    added_finding = next(
        finding
        for finding in result.findings
        if finding.classification is ChangeClassification.ADDED
    )
    assert removed_finding.old_evidence.citations[0].document_version_id == old_version
    assert not removed_finding.new_evidence.citations
    assert added_finding.new_evidence.citations[0].document_version_id == new_version
    assert not any(finding.potential_conflict for finding in result.findings)


def test_rename_detection_does_not_claim_a_contradiction() -> None:
    project, old_version, new_version = uuid4(), uuid4(), uuid4()
    old = entity(project, "Brake Controller")
    new = entity(project, "BrakeController")

    result = RevisionComparisonService().compare(
        project, snapshot(old_version, [old]), snapshot(new_version, [new])
    )

    finding = result.findings[0]
    assert finding.classification is ChangeClassification.RENAMED
    assert finding.old_evidence.citations and finding.new_evidence.citations
    assert not finding.potential_conflict


def test_relationship_target_change_preserves_old_and_new_evidence() -> None:
    project, old_version, new_version = uuid4(), uuid4(), uuid4()
    source_id = uuid4()
    source_old = entity(project, "Controller", entity_id=source_id)
    source_new = entity(project, "Controller", entity_id=source_id)
    target_old = entity(project, "LegacyInterface")
    target_new = entity(project, "NewInterface")
    old = relationship(project, source_old, target_old, "REQUIRES")
    new = relationship(project, source_new, target_new, "REQUIRES")
    base = snapshot(
        old_version,
        [source_old, target_old],
        [old],
        relationship_evidence={old.id: evidence(old_version, "requires legacy")},
    )
    target = snapshot(
        new_version,
        [source_new, target_new],
        [new],
        relationship_evidence={new.id: evidence(new_version, "requires new")},
    )

    result = RevisionComparisonService().compare(project, base, target)
    finding = next(
        item
        for item in result.findings
        if item.classification is ChangeClassification.TARGET_CHANGED
    )

    assert finding.old_evidence.citations[0].document_version_id == old_version
    assert finding.new_evidence.citations[0].document_version_id == new_version


def test_version_and_project_isolation_exclude_unrelated_graph_facts() -> None:
    project, other_project = uuid4(), uuid4()
    old_version, new_version = uuid4(), uuid4()
    local = entity(project, "Local")
    foreign = entity(other_project, "Foreign")
    stale = RevisionEvidence(citations=[*evidence(uuid4(), "stale").citations])
    result = RevisionComparisonService().compare(
        project,
        snapshot(old_version, [local, foreign], entity_evidence={local.id: stale}),
        snapshot(
            new_version,
            [local, foreign],
            entity_evidence={local.id: evidence(new_version, "local")},
        ),
    )

    assert all(finding.entity_id != foreign.id for finding in result.findings)
    assert {finding.classification for finding in result.findings} == {
        ChangeClassification.ADDED
    }
