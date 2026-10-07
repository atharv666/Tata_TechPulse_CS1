"""Semantic, bounded impact-analysis tests with provenance and isolation checks."""

from decimal import Decimal
from uuid import UUID, uuid4

from app.models.enums import ExtractionType, TrustState, ValidationState
from app.models.schema import Entity, Relationship
from app.retrieval.evidence import Citation, GraphFactEvidence
from app.retrieval.impact import (
    ImpactAnalysisService,
    ImpactKind,
    ImpactSourceEvidence,
)


def entity(project_id: UUID, name: str, entity_type: str) -> Entity:
    return Entity(
        id=uuid4(),
        project_id=project_id,
        canonical_name=name,
        normalized_name=name.casefold(),
        entity_type=entity_type,
        trust_state=TrustState.CANDIDATE,
        extraction_type=ExtractionType.EXPLICIT,
        validation_state=ValidationState.PENDING,
        confidence=Decimal("0.800"),
        extraction_metadata={},
    )


def relationship(
    project_id: UUID, source: Entity, target: Entity, kind: str = "REQUIRES"
) -> Relationship:
    return Relationship(
        id=uuid4(),
        project_id=project_id,
        source_entity_id=source.id,
        target_entity_id=target.id,
        relationship_type=kind,
        trust_state=TrustState.CANDIDATE,
        extraction_type=ExtractionType.INFERRED,
        validation_state=ValidationState.PENDING,
        confidence=Decimal("0.750"),
        attributes={},
    )


def source_evidence(
    relationship_id: UUID, version: UUID, inferred: bool = True
) -> ImpactSourceEvidence:
    chunk_id = uuid4()
    return ImpactSourceEvidence(
        fact=GraphFactEvidence(
            fact_id=str(relationship_id),
            source_entity="source",
            relationship_type="REQUIRES",
            target_entity="target",
            confidence=0.75,
            extraction_type=ExtractionType.INFERRED
            if inferred
            else ExtractionType.EXPLICIT,
            validation_state=ValidationState.PENDING,
            citation_ids=[f"chunk:{chunk_id}"],
        ),
        citations=[
            Citation(
                citation_id=f"chunk:{chunk_id}",
                chunk_id=chunk_id,
                document_id=uuid4(),
                document_version_id=version,
                document_name="HLD",
                section_heading="Interfaces",
                page_start=1,
                page_end=1,
                excerpt="The source requires the target.",
            )
        ],
    )


def test_direct_and_indirect_impacts_reconstruct_paths_and_keep_inference_label() -> (
    None
):
    project, version = uuid4(), uuid4()
    interface = entity(project, "WheelSpeedInterface", "INTERFACE")
    controller = entity(project, "BrakeController", "COMPONENT")
    function = entity(project, "BrakeFunction", "FUNCTION")
    direct = relationship(project, controller, interface)
    indirect = relationship(project, function, controller, "DEPENDS_ON")
    result = ImpactAnalysisService().analyze(
        project,
        interface.id,
        [interface, controller, function],
        [direct, indirect],
        {
            direct.id: source_evidence(direct.id, version),
            indirect.id: source_evidence(indirect.id, version),
        },
        document_version_id=version,
    )

    assert [item.kind for item in result.results] == [
        ImpactKind.DIRECT_IMPACT,
        ImpactKind.INDIRECT_IMPACT,
    ]
    assert result.results[1].path.entity_ids == (
        interface.id,
        controller.id,
        function.id,
    )
    assert result.results[0].extraction_type is ExtractionType.INFERRED
    assert (
        result.results[0].source_evidence[0].citations[0].document_version_id == version
    )


def test_bounded_analysis_and_missing_traceability_are_reported() -> None:
    project, version = uuid4(), uuid4()
    interface = entity(project, "Telemetry", "INTERFACE")
    first = entity(project, "ConsumerA", "COMPONENT")
    second = entity(project, "ConsumerB", "COMPONENT")
    edge_one = relationship(project, first, interface)
    edge_two = relationship(project, second, first)
    result = ImpactAnalysisService().analyze(
        project,
        interface.id,
        [interface, first, second],
        [edge_one, edge_two],
        {edge_one.id: source_evidence(edge_one.id, version)},
        depth=1,
        edge_limit=1,
    )

    assert len(result.results) == 1
    assert result.truncated is False
    assert result.results[0].kind is ImpactKind.DIRECT_IMPACT
    missing = ImpactAnalysisService().analyze(
        project,
        interface.id,
        [interface, first],
        [edge_one],
        {},
        document_version_id=version,
    )
    assert missing.results[0].kind is ImpactKind.INSUFFICIENT_TRACEABILITY


def test_project_and_version_isolation_exclude_unrelated_or_stale_evidence() -> None:
    project, other_project = uuid4(), uuid4()
    version, older_version = uuid4(), uuid4()
    interface = entity(project, "DataInterface", "INTERFACE")
    consumer = entity(project, "Consumer", "COMPONENT")
    local_edge = relationship(project, consumer, interface)
    foreign_root = entity(other_project, "Foreign", "INTERFACE")
    foreign_consumer = entity(other_project, "ForeignConsumer", "COMPONENT")
    foreign_edge = relationship(other_project, foreign_consumer, foreign_root)
    stale = ImpactAnalysisService().analyze(
        project,
        interface.id,
        [interface, consumer, foreign_root, foreign_consumer],
        [local_edge, foreign_edge],
        {local_edge.id: source_evidence(local_edge.id, older_version)},
        document_version_id=version,
    )

    assert len(stale.results) == 1
    assert stale.results[0].affected_entity_id == consumer.id
    assert stale.results[0].kind is ImpactKind.INSUFFICIENT_TRACEABILITY
