"""Relationship binding, the idempotent graph build, and persisted findings (PostgreSQL)."""

from __future__ import annotations

import random
from decimal import Decimal

import pytest
from app.canonicalization.binding import RelationshipBinder
from app.graph.build import GraphBuildService
from app.models.enums import ExtractionType, SourceClassification, ValidationState
from app.models.schema import (
    Finding,
    MergeDecision,
    Relationship,
    RelationshipCandidate,
    RelationshipEvidence,
    ValidationEvent,
)
from app.services.findings import (
    FindingNotFoundError,
    FindingsService,
    FindingStateError,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.support.graph import GraphBuilder

pytestmark = pytest.mark.usefixtures("clean_database")


def build(session: Session, graph: GraphBuilder):  # type: ignore[no-untyped-def]
    result = GraphBuildService().build(session, graph.project_id, "builder")
    session.flush()
    return result


def relationships(session: Session, graph: GraphBuilder) -> list[Relationship]:
    return list(
        session.scalars(
            select(Relationship).where(Relationship.project_id == graph.project_id)
        )
    )


def findings(
    session: Session, graph: GraphBuilder, kind: str | None = None
) -> list[Finding]:
    query = select(Finding).where(Finding.project_id == graph.project_id)
    if kind:
        query = query.where(Finding.finding_type == kind)
    return list(session.scalars(query.order_by(Finding.summary)))


# -- binding -------------------------------------------------------------------------------------
def test_candidates_are_bound_to_entities_with_their_evidence(
    db_session: Session,
) -> None:
    graph = GraphBuilder(db_session)
    controller = graph.entity("BrakeController")
    interface = graph.entity("WheelSpeedInterface", "INTERFACE")
    candidate = graph.candidate("BrakeController", "REQUIRES", "WheelSpeedInterface")

    result = RelationshipBinder().bind(db_session, graph.project_id)

    assert result.bound == 1 and result.relationships_created == 1
    row = relationships(db_session, graph)[0]
    assert (row.source_entity_id, row.target_entity_id) == (controller.id, interface.id)
    assert row.validation_state is ValidationState.PENDING
    evidence = db_session.scalars(select(RelationshipEvidence)).one()
    assert (
        evidence.chunk_id == candidate.chunk_id
        and evidence.excerpt == candidate.excerpt
    )
    db_session.refresh(candidate)
    assert candidate.status == "BOUND" and candidate.relationship_id == row.id


def test_binding_does_not_depend_on_the_order_candidates_were_staged(
    db_session: Session,
) -> None:
    statements = [
        ("A", "REQUIRES", "I1"),
        ("B", "PROVIDES", "I1"),
        ("A", "USES", "B"),
        ("C", "CONSUMES", "I2"),
    ]
    outcomes = []
    for attempt in range(3):
        graph = GraphBuilder(db_session, f"binding-{attempt}")
        ids = {
            name: graph.entity(
                name, "INTERFACE" if name.startswith("I") else "COMPONENT"
            ).id
            for name in ("A", "B", "C", "I1", "I2")
        }
        shuffled = statements[:]
        random.Random(attempt).shuffle(shuffled)
        for source, kind, target in shuffled:
            graph.candidate(source, kind, target)
        RelationshipBinder().bind(db_session, graph.project_id)
        names = {value: key for key, value in ids.items()}
        outcomes.append(
            {
                (
                    names[r.source_entity_id],
                    r.relationship_type,
                    names[r.target_entity_id],
                )
                for r in relationships(db_session, graph)
            }
        )
    assert outcomes[0] == outcomes[1] == outcomes[2] == set(statements)


def test_an_alias_resolves_to_its_owner(db_session: Session) -> None:
    graph = GraphBuilder(db_session)
    owner = graph.entity("BrakeController", aliases=("BrakeCtrl",))
    interface = graph.entity("WheelSpeedInterface", "INTERFACE")
    graph.candidate("BrakeCtrl", "REQUIRES", "WheelSpeedInterface")

    RelationshipBinder().bind(db_session, graph.project_id)

    row = relationships(db_session, graph)[0]
    assert row.source_entity_id == owner.id and row.target_entity_id == interface.id


def test_an_undefined_endpoint_stays_unbound_and_becomes_one_grouped_finding(
    db_session: Session,
) -> None:
    graph = GraphBuilder(db_session)
    graph.entity("BrakeController")
    graph.entity("DiagController")
    first = graph.candidate("BrakeController", "REQUIRES", "GhostInterface")
    graph.candidate("DiagController", "USES", "GhostInterface")

    result = build(db_session, graph)

    assert result.candidates_unbound == 2 and result.relationships_created == 0
    db_session.refresh(first)
    assert first.status == "UNBOUND" and "not defined" in (first.note or "")
    [finding] = findings(db_session, graph, "MISSING_ENTITY_DEFINITION")
    assert finding.summary.startswith("Potential inconsistency detected:")
    assert "GhostInterface" in finding.summary and "2 relationship" in finding.summary
    assert len(finding.details["statements"]) == 2


def test_a_name_shared_by_two_types_is_bound_only_when_the_rule_picks_one(
    db_session: Session,
) -> None:
    graph = GraphBuilder(db_session)
    graph.entity("Carrier", "INTERFACE")
    graph.entity("User", "COMPONENT")
    signal = graph.entity("BrakeStatus", "SIGNAL")
    graph.entity("BrakeStatus", "INTERFACE")
    graph.candidate(
        "Carrier", "CARRIES", "BrakeStatus"
    )  # CARRIES ends at signals: unambiguous
    graph.candidate("User", "REQUIRES", "BrakeStatus")  # interface or signal: ambiguous

    result = RelationshipBinder().bind(db_session, graph.project_id)

    assert result.bound == 1 and result.ambiguous_endpoint == 1
    [row] = relationships(db_session, graph)
    assert row.relationship_type == "CARRIES" and row.target_entity_id == signal.id


def test_an_endpoint_a_reviewer_rejected_is_not_bound(db_session: Session) -> None:
    graph = GraphBuilder(db_session)
    graph.entity("BrakeController")
    graph.entity("OldInterface", "INTERFACE", state=ValidationState.REJECTED)
    graph.candidate("BrakeController", "REQUIRES", "OldInterface")

    result = build(db_session, graph)

    assert result.relationships_created == 0
    [finding] = findings(db_session, graph, "DANGLING_RELATIONSHIP")
    assert "rejected" in finding.summary


def test_repeated_statements_make_one_relationship_with_the_best_claim(
    db_session: Session,
) -> None:
    graph = GraphBuilder(db_session)
    graph.entity("A")
    graph.entity("I", "INTERFACE")
    graph.candidate("A", "USES", "I", confidence="0.600", extraction="INFERRED")
    graph.candidate("A", "USES", "I", confidence="0.900", extraction="EXPLICIT")

    RelationshipBinder().bind(db_session, graph.project_id)

    [row] = relationships(db_session, graph)
    assert (
        row.raw_confidence == Decimal("0.900")
        and row.extraction_type is ExtractionType.EXPLICIT
    )
    assert db_session.scalar(select(func.count(RelationshipEvidence.id))) == 2


def test_a_relationship_a_reviewer_rejected_is_not_resurrected(
    db_session: Session,
) -> None:
    graph = GraphBuilder(db_session)
    source, target = graph.entity("A"), graph.entity("I", "INTERFACE")
    graph.candidate("A", "USES", "I")
    RelationshipBinder().bind(db_session, graph.project_id)
    [row] = relationships(db_session, graph)
    row.validation_state = ValidationState.REJECTED
    db_session.flush()

    graph.candidate("A", "USES", "I")  # the same statement in another section
    RelationshipBinder().bind(db_session, graph.project_id)

    [row] = relationships(db_session, graph)
    assert row.validation_state is ValidationState.REJECTED
    assert (row.source_entity_id, row.target_entity_id) == (source.id, target.id)


# -- idempotent build ---------------------------------------------------------------------------
def test_confidence_is_a_pure_function_so_rebuilding_never_compounds_it(
    db_session: Session,
) -> None:
    graph = GraphBuilder(db_session)
    inferred = graph.entity(
        "Soft", confidence="0.900", extraction=ExtractionType.INFERRED
    )
    first = build(db_session, graph)
    after_first = db_session.scalar(select(Relationship.id)), inferred.confidence
    for _ in range(3):
        build(db_session, graph)
    db_session.refresh(inferred)
    assert inferred.confidence == Decimal("0.765")  # 0.9 * 0.85, however many builds
    assert inferred.raw_confidence == Decimal("0.900")
    assert after_first[1] == inferred.confidence and first.validated_entities == 1


def test_rebuilding_changes_nothing_and_writes_no_new_events(
    db_session: Session,
) -> None:
    graph = GraphBuilder(db_session)
    graph.entity("BrakeController")
    graph.entity("WheelSpeedInterface", "INTERFACE")
    graph.candidate("BrakeController", "REQUIRES", "WheelSpeedInterface")
    build(db_session, graph)

    def snapshot() -> tuple[object, ...]:
        return (
            db_session.scalar(select(func.count(ValidationEvent.id))),
            db_session.scalar(select(func.count(Relationship.id))),
            db_session.scalar(select(func.count(RelationshipEvidence.id))),
            db_session.scalar(select(func.count(Finding.id))),
            sorted(str(r.confidence) for r in relationships(db_session, graph)),
        )

    before = snapshot()
    again = build(db_session, graph)
    assert snapshot() == before
    assert again.findings_opened == 0 and again.relationships_created == 0


def test_human_reviewed_facts_are_left_alone_by_a_rebuild(db_session: Session) -> None:
    graph = GraphBuilder(db_session)
    verified = graph.entity(
        "Verified", state=ValidationState.HUMAN_VERIFIED, confidence="0.500"
    )
    build(db_session, graph)
    db_session.refresh(verified)
    assert verified.validation_state is ValidationState.HUMAN_VERIFIED
    assert verified.confidence == Decimal("0.500")


def test_an_entity_without_evidence_is_rejected_once_with_a_reason(
    db_session: Session,
) -> None:
    graph = GraphBuilder(db_session)
    orphan = graph.entity("Orphan", evidence=False)

    first = build(db_session, graph)
    build(db_session, graph)

    db_session.refresh(orphan)
    assert (
        orphan.validation_state is ValidationState.REJECTED
        and first.rejected_entities == 1
    )
    events = db_session.scalars(select(ValidationEvent)).all()
    assert len(events) == 1 and "no source evidence" in (events[0].reason or "")


def test_ocr_only_evidence_discounts_confidence_and_keeps_the_label(
    db_session: Session,
) -> None:
    graph = GraphBuilder(db_session)
    graph.entity("A")
    graph.entity("I", "INTERFACE")
    row = graph.candidate("A", "USES", "I", confidence="0.900")
    row.source_classification = SourceClassification.OCR_TEXT.value
    build(db_session, graph)
    [relationship] = relationships(db_session, graph)
    assert relationship.confidence == Decimal("0.855")  # 0.9 * 0.95
    evidence = db_session.scalars(select(RelationshipEvidence)).one()
    assert evidence.source_classification is SourceClassification.OCR_TEXT


# -- findings ------------------------------------------------------------------------------------
def test_a_missing_provider_finding_opens_and_resolves_itself(
    db_session: Session,
) -> None:
    graph = GraphBuilder(db_session)
    graph.entity("Consumer")
    graph.entity("Provider")
    graph.entity("WheelSpeedInterface", "INTERFACE")
    graph.candidate("Consumer", "REQUIRES", "WheelSpeedInterface")

    build(db_session, graph)
    [finding] = findings(db_session, graph, "MISSING_PROVIDER")
    assert (
        finding.status == "OPEN" and finding.severity == "HIGH"
    )  # someone requires it
    assert finding.summary.startswith("Potential inconsistency detected:")
    assert finding.confidence is not None

    graph.candidate("Provider", "PROVIDES", "WheelSpeedInterface")
    result = build(db_session, graph)
    db_session.refresh(finding)
    assert finding.status == "RESOLVED" and result.findings_resolved == 1


def test_a_dismissed_finding_stays_dismissed_across_rebuilds(
    db_session: Session,
) -> None:
    graph = GraphBuilder(db_session)
    graph.entity("Lonely", "INTERFACE")
    build(db_session, graph)
    [finding] = findings(db_session, graph, "MISSING_PROVIDER")
    service = FindingsService(db_session, graph.project_id, "reviewer")

    with pytest.raises(ValueError, match="reason is required"):
        service.dismiss(finding.id, "  ")
    service.dismiss(finding.id, "Provided by the platform, outside this HLD.")
    build(db_session, graph)
    build(db_session, graph)

    db_session.refresh(finding)
    assert finding.status == "DISMISSED"
    assert finding.dismissed_by == "reviewer" and "platform" in (
        finding.dismissed_reason or ""
    )
    assert len(findings(db_session, graph, "MISSING_PROVIDER")) == 1

    service.reopen(finding.id)
    assert finding.status == "OPEN"
    with pytest.raises(FindingStateError):
        service.reopen(finding.id)


def test_findings_are_project_scoped(db_session: Session) -> None:
    graph, other = GraphBuilder(db_session, "a"), GraphBuilder(db_session, "b")
    graph.entity("Lonely", "INTERFACE")
    build(db_session, graph)
    [finding] = findings(db_session, graph)
    with pytest.raises(FindingNotFoundError):
        FindingsService(db_session, other.project_id, "x").get(finding.id)
    rows, total = FindingsService(db_session, graph.project_id, "x").list(status="OPEN")
    assert total == 1 and rows[0].id == finding.id


def test_conflicting_declarations_and_unusual_relationship_types_are_flagged(
    db_session: Session,
) -> None:
    graph = GraphBuilder(db_session)
    graph.entity("Ctrl")
    graph.entity("Bus", "INTERFACE")
    graph.entity("Dup", "INTERFACE")
    graph.entity("Dup", "SIGNAL")
    graph.candidate("Ctrl", "PROVIDES", "Bus")
    graph.candidate("Ctrl", "CONSUMES", "Bus")  # opposing statements about one pair
    graph.candidate(
        "Bus", "REQUIRES", "Ctrl"
    )  # an interface does not require a component

    build(db_session, graph)

    conflicts = findings(db_session, graph, "CONFLICTING_DECLARATION")
    assert len(conflicts) == 2  # the opposing pair and the doubly-declared name
    assert any("PROVIDES and CONSUMES" in item.summary for item in conflicts)
    assert any("more than one kind" in item.summary for item in conflicts)
    [unusual] = findings(db_session, graph, "INCONSISTENT_RELATIONSHIP_TYPE")
    assert "REQUIRES" in unusual.summary


def test_every_finding_uses_the_potential_inconsistency_wording(
    db_session: Session,
) -> None:
    graph = GraphBuilder(db_session)
    graph.entity("Lonely", "INTERFACE")
    graph.entity("A")
    graph.candidate("A", "USES", "Missing")
    build(db_session, graph)
    rows = findings(db_session, graph)
    assert rows and all(
        row.summary.startswith("Potential inconsistency detected:") for row in rows
    )


def test_a_pair_the_model_was_unsure_about_becomes_a_possible_duplicate_finding(
    db_session: Session,
) -> None:
    graph = GraphBuilder(db_session)
    first = graph.entity("Wheel Speed Sensor", "COMPONENT")
    second = graph.entity("WSS", "COMPONENT")
    db_session.add(
        MergeDecision(
            project_id=graph.project_id,
            pair_key="k" * 64,
            entity_a_id=first.id,
            entity_b_id=second.id,
            decision="UNSURE",
            source="LLM",
            reason="Could be the same sensor.",
            fingerprint="f",
        )
    )
    build(db_session, graph)
    [finding] = findings(db_session, graph, "POSSIBLE_DUPLICATE")
    assert "may be the same" in finding.summary
    assert finding.details["reason"] == "Could be the same sensor."


def test_an_alias_claimed_by_two_entities_is_reported(db_session: Session) -> None:
    graph = GraphBuilder(db_session)
    entity = graph.entity("Second")
    entity.extraction_metadata = {"alias_conflicts": ["Shared"]}
    db_session.flush()
    build(db_session, graph)
    [finding] = findings(db_session, graph, "UNRESOLVED_ALIAS")
    assert "Shared" in finding.summary


def test_unbound_candidates_are_never_dropped(db_session: Session) -> None:
    graph = GraphBuilder(db_session)
    graph.entity("A")
    graph.candidate("A", "USES", "Missing")
    build(db_session, graph)
    assert db_session.scalar(select(func.count(RelationshipCandidate.id))) == 1
