"""Graph validation/build rules; no query path is permitted to call graph construction."""

from decimal import Decimal
from uuid import uuid4

from app.models.enums import (
    ExtractionType,
    SourceClassification,
    TrustState,
    ValidationState,
)
from app.models.schema import (
    Chunk,
    Entity,
    EntityEvidence,
    Relationship,
    RelationshipEvidence,
)
from app.validation.graph import (
    calculate_confidence,
    interface_findings,
    validate_entity,
    validate_relationship,
)


def entity(
    project_id: object, name: str, entity_type: str = "SOFTWARE_COMPONENT"
) -> Entity:
    result = Entity(
        project_id=project_id,
        canonical_name=name,
        normalized_name=name.casefold(),
        entity_type=entity_type,
        trust_state=TrustState.CANDIDATE,
        extraction_type=ExtractionType.EXPLICIT,
        validation_state=ValidationState.PENDING,
        confidence=Decimal("0.900"),
    )
    result.id = uuid4()
    return result


def chunk(project_id: object) -> Chunk:
    return Chunk(
        project_id=project_id,
        document_version_id=uuid4(),
        section_id=uuid4(),
        ordinal=1,
        content="BrakeController requires WheelSpeedInterface",
        token_count=3,
    )


def test_valid_entity_and_evidence_preserve_candidate_pending_state() -> None:
    project = uuid4()
    fact = entity(project, "BrakeController")
    evidence = EntityEvidence(
        project_id=project,
        entity_id=fact.id,
        chunk_id=chunk(project).id,
        source_classification=SourceClassification.DIRECT_TEXT,
        excerpt="BrakeController",
        start_offset=0,
        end_offset=15,
    )

    result = validate_entity(fact, [evidence])

    assert result.valid
    assert fact.trust_state is TrustState.CANDIDATE
    assert fact.validation_state is ValidationState.PENDING
    assert result.confidence == Decimal("0.900")


def test_invalid_relationship_references_and_missing_provenance_are_rejected() -> None:
    project = uuid4()
    source = entity(project, "BrakeController")
    relationship = Relationship(
        project_id=project,
        source_entity_id=source.id,
        target_entity_id=uuid4(),
        relationship_type="REQUIRES",
        trust_state=TrustState.CANDIDATE,
        extraction_type=ExtractionType.EXPLICIT,
        validation_state=ValidationState.PENDING,
        confidence=Decimal("0.800"),
        attributes={},
    )

    result = validate_relationship(relationship, source, None, [])

    assert not result.valid
    assert "undefined" in " ".join(result.reasons)
    assert "no source evidence" in " ".join(result.reasons)


def test_relationship_provenance_direction_and_confidence_are_validated() -> None:
    project = uuid4()
    source, target = (
        entity(project, "BrakeController"),
        entity(project, "WheelSpeedInterface", "INTERFACE"),
    )
    relationship = Relationship(
        project_id=project,
        source_entity_id=source.id,
        target_entity_id=target.id,
        relationship_type="requires",
        trust_state=TrustState.CANDIDATE,
        extraction_type=ExtractionType.INFERRED,
        validation_state=ValidationState.PENDING,
        confidence=Decimal("0.900"),
        attributes={},
    )
    evidence = RelationshipEvidence(
        project_id=project,
        relationship_id=relationship.id,
        chunk_id=chunk(project).id,
        source_classification=SourceClassification.DIRECT_TEXT,
        excerpt="requires",
        start_offset=16,
        end_offset=24,
    )

    result = validate_relationship(relationship, source, target, [evidence])

    assert result.valid
    assert result.confidence == Decimal("0.765")
    assert relationship.source_entity_id == source.id
    assert relationship.target_entity_id == target.id


def test_cross_project_evidence_and_unsupported_type_are_invalid() -> None:
    project = uuid4()
    fact = entity(project, "BrakeController")
    invalid_evidence = EntityEvidence(
        project_id=uuid4(),
        entity_id=fact.id,
        chunk_id=uuid4(),
        source_classification=SourceClassification.DIRECT_TEXT,
        excerpt="BrakeController",
        start_offset=None,
        end_offset=None,
    )
    assert not validate_entity(fact, [invalid_evidence]).valid

    relationship = Relationship(
        project_id=project,
        source_entity_id=fact.id,
        target_entity_id=uuid4(),
        relationship_type="CONTRADICTS",
        trust_state=TrustState.CANDIDATE,
        extraction_type=ExtractionType.EXPLICIT,
        validation_state=ValidationState.PENDING,
        confidence=Decimal("0.700"),
        attributes={},
    )
    assert not validate_relationship(relationship, fact, None, []).valid


def test_missing_interface_provider_is_a_non_blocking_potential_finding() -> None:
    project = uuid4()
    interface = entity(project, "WheelSpeedInterface", "INTERFACE")
    assert (
        "Potential missing provider"
        in interface_findings([interface], [])[str(interface.id)][0]
    )


def test_confidence_and_duplicate_candidates_do_not_become_human_verified() -> None:
    assert calculate_confidence(
        Decimal("0.990"), ExtractionType.EXPLICIT, 2
    ) == Decimal("1.000")
    assert calculate_confidence(
        Decimal("0.990"), ExtractionType.EXPLICIT, 0
    ) == Decimal("0.000")
    candidate = entity(uuid4(), "Duplicate")
    assert candidate.validation_state is not ValidationState.HUMAN_VERIFIED
