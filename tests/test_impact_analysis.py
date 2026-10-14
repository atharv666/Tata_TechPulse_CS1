"""Change-impact analysis over the knowledge graph (PostgreSQL traversal, with provenance)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.canonicalization.merge import apply_merge
from app.core.errors import ConflictError, NotFoundError
from app.models.enums import ExtractionType, ValidationState
from app.models.schema import DocumentVersion
from app.retrieval.impact import ImpactAnalysisService, ImpactKind
from sqlalchemy.orm import Session

from tests.support.graph import GraphBuilder

pytestmark = pytest.mark.usefixtures("clean_database")


def analyze(session: Session, graph: GraphBuilder, root, **kwargs):  # type: ignore[no-untyped-def]
    return ImpactAnalysisService(session, graph.project_id).analyze(root.id, **kwargs)


def by_name(result):  # type: ignore[no-untyped-def]
    return {item.affected_entity_name: item for item in result.results}


def scenario(session: Session):  # type: ignore[no-untyped-def]
    """Consumer REQUIRES Interface; Provider PROVIDES Interface; Top USES Consumer."""
    graph = GraphBuilder(session)
    interface = graph.entity("WheelSpeedInterface", "INTERFACE")
    consumer = graph.entity("BrakeController")
    provider = graph.entity("WheelSpeedSensor")
    top = graph.entity("VehicleManager")
    graph.relationship(consumer, "REQUIRES", interface, confidence="0.900")
    graph.relationship(provider, "PROVIDES", interface, confidence="0.950")
    graph.relationship(
        top, "USES", consumer, confidence="0.800", extraction=ExtractionType.INFERRED
    )
    return graph, interface, consumer, provider, top


def test_direct_and_indirect_impacts_keep_paths_labels_and_weakest_link(
    db_session: Session,
) -> None:
    graph, interface, consumer, provider, top = scenario(db_session)

    result = analyze(db_session, graph, interface, depth=2)

    found = by_name(result)
    assert set(found) == {"BrakeController", "WheelSpeedSensor", "VehicleManager"}
    direct, indirect = found["BrakeController"], found["VehicleManager"]
    assert direct.kind is ImpactKind.DIRECT_IMPACT and direct.hops == 1
    assert indirect.kind is ImpactKind.INDIRECT_IMPACT and indirect.hops == 2
    assert indirect.path.entity_ids == (interface.id, consumer.id, top.id)
    assert indirect.via == [
        "BrakeController REQUIRES WheelSpeedInterface",
        "VehicleManager USES BrakeController",
    ]
    # the chain is as strong as its weakest link and is labelled INFERRED if any link is
    assert indirect.confidence == pytest.approx(0.8)
    assert indirect.extraction_type is ExtractionType.INFERRED
    assert direct.extraction_type is ExtractionType.EXPLICIT
    assert direct.validation_state is ValidationState.PENDING
    assert [e.fact.relationship_type for e in indirect.source_evidence] == [
        "REQUIRES",
        "USES",
    ]
    assert all(e.citations for e in indirect.source_evidence)
    assert result.root_entity_name == "WheelSpeedInterface" and not result.truncated
    assert result.summary == {"SOFTWARE_COMPONENT": 3}
    assert any("not confirmed impacts" in note for note in result.notes)


def test_providers_are_affected_when_their_interface_changes(
    db_session: Session,
) -> None:
    graph, interface, *_ = scenario(db_session)
    found = by_name(analyze(db_session, graph, interface, depth=1))
    assert (
        found["WheelSpeedSensor"].kind is ImpactKind.DIRECT_IMPACT
    )  # PROVIDES was missing once


def test_a_provider_change_reaches_the_consumers_of_what_it_provides(
    db_session: Session,
) -> None:
    graph, interface, consumer, provider, _ = scenario(db_session)
    found = by_name(analyze(db_session, graph, provider, depth=2))
    assert found["WheelSpeedInterface"].hops == 1
    assert found["BrakeController"].hops == 2  # provider -> interface -> its consumer


def test_flows_and_tests_are_followed_downstream(db_session: Session) -> None:
    graph = GraphBuilder(db_session)
    requirement = graph.entity("REQ_Braking", "REQUIREMENT")
    component = graph.entity("BrakeController")
    test_case = graph.entity("TC_Braking_01", "TEST_CASE")
    first = graph.entity("SlipEstimation", "FUNCTIONAL_FLOW")
    second = graph.entity("ValveActuation", "FUNCTIONAL_FLOW")
    graph.relationship(requirement, "IMPLEMENTED_BY", component)
    graph.relationship(component, "VERIFIED_BY", test_case)
    graph.relationship(first, "PRECEDES", second)

    from_requirement = analyze(db_session, graph, requirement, depth=2)
    assert set(by_name(from_requirement)) == {"BrakeController", "TC_Braking_01"}
    assert from_requirement.affected_tests == ["TC_Braking_01"]
    downstream = by_name(analyze(db_session, graph, first, depth=1))
    assert set(downstream) == {"ValveActuation"}
    assert (
        by_name(analyze(db_session, graph, second, depth=1)) == {}
    )  # nothing is downstream


def test_depth_and_node_limits_are_enforced(db_session: Session) -> None:
    graph = GraphBuilder(db_session)
    hub = graph.entity("Hub", "INTERFACE")
    for index in range(6):
        graph.relationship(graph.entity(f"User{index}"), "USES", hub)
    with pytest.raises(ValueError, match="bounds"):
        analyze(db_session, graph, hub, depth=4)
    limited = analyze(db_session, graph, hub, depth=1, node_limit=3)
    assert len(limited.results) == 3 and limited.truncated


def test_evidence_from_another_version_is_reported_as_insufficient_traceability(
    db_session: Session,
) -> None:
    graph, interface, *_ = scenario(db_session)
    other_version = DocumentVersion(
        project_id=graph.project_id,
        document_id=graph.version.document_id,
        version_number=2,
        checksum="y" * 64,
    )
    db_session.add(other_version)
    db_session.flush()

    scoped = analyze(
        db_session, graph, interface, depth=1, document_version_id=other_version.id
    )
    assert {i.kind for i in scoped.results} == {ImpactKind.INSUFFICIENT_TRACEABILITY}
    assert all("no source evidence" in (i.message or "") for i in scoped.results)
    current = analyze(
        db_session, graph, interface, depth=1, document_version_id=graph.version.id
    )
    assert {i.kind for i in current.results} == {ImpactKind.DIRECT_IMPACT}


def test_rejected_replaced_and_merged_facts_do_not_propagate(
    db_session: Session,
) -> None:
    graph = GraphBuilder(db_session)
    interface = graph.entity("Interface", "INTERFACE")
    rejected_user, kept_user, dup = (
        graph.entity("RejectedUser"),
        graph.entity("KeptUser"),
        graph.entity("DupUser"),
    )
    survivor = graph.entity("Survivor")
    graph.relationship(rejected_user, "USES", interface, state=ValidationState.REJECTED)
    graph.relationship(kept_user, "USES", interface)
    graph.relationship(dup, "USES", interface)
    apply_merge(db_session, survivor, dup, decided_by="HUMAN", actor_id="r")

    found = set(by_name(analyze(db_session, graph, interface, depth=1)))

    assert found == {"KeptUser", "Survivor"}


def test_the_root_must_be_a_live_entity_of_the_project(db_session: Session) -> None:
    graph, other = GraphBuilder(db_session, "a"), GraphBuilder(db_session, "b")
    foreign = other.entity("Foreign")
    live, gone = graph.entity("Live"), graph.entity("Gone")
    apply_merge(db_session, live, gone, decided_by="HUMAN", actor_id="r")
    service = ImpactAnalysisService(db_session, graph.project_id)
    with pytest.raises(NotFoundError):
        service.analyze(foreign.id)
    with pytest.raises(NotFoundError):
        service.analyze(uuid4())
    with pytest.raises(ConflictError, match="merged, replaced or rejected"):
        service.analyze(gone.id)


def test_impact_never_crosses_project_boundaries(db_session: Session) -> None:
    one, two = GraphBuilder(db_session, "one"), GraphBuilder(db_session, "two")
    interface = one.entity("Interface", "INTERFACE")
    one.relationship(one.entity("Mine"), "USES", interface)
    foreign_interface = two.entity("Interface", "INTERFACE")
    two.relationship(two.entity("Theirs"), "USES", foreign_interface)
    assert set(by_name(analyze(db_session, one, interface))) == {"Mine"}
