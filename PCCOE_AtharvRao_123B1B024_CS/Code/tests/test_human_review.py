"""Human review against PostgreSQL: decisions preserve the AI extraction and its history."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from app.canonicalization.merge import apply_merge
from app.core.errors import ConflictError, NotFoundError
from app.graph.build import GraphBuildService
from app.models.enums import MembershipRole, TrustState, ValidationState
from app.models.schema import (
    Entity,
    EntityAlias,
    EntityEvidence,
    Relationship,
    RelationshipEvidence,
)
from app.repositories.review import ReviewRepository
from app.services.review import ReviewActor, ReviewPermissionError, ReviewService
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.support.graph import GraphBuilder

pytestmark = pytest.mark.usefixtures("clean_database")


def reviewer(
    session: Session,
    graph: GraphBuilder,
    role: MembershipRole = MembershipRole.REVIEWER,
) -> ReviewService:
    return ReviewService(
        ReviewRepository(session, graph.project_id),
        ActorFor(graph.project_id, role).actor,
    )


class ActorFor:
    def __init__(self, project_id, role: MembershipRole) -> None:  # type: ignore[no-untyped-def]
        self.actor = ReviewActor("reviewer-1", project_id, role)


def edge(
    session: Session, graph: GraphBuilder, source: Entity, kind: str, target: Entity
) -> Relationship:
    graph.candidate(source.canonical_name, kind, target.canonical_name)
    GraphBuildService().build(session, graph.project_id, "builder")
    session.flush()
    return session.scalars(
        select(Relationship).where(
            Relationship.source_entity_id == source.id,
            Relationship.target_entity_id == target.id,
            Relationship.relationship_type == kind,
        )
    ).one()


# -- entity decisions ----------------------------------------------------------------------------
def test_verify_marks_the_candidate_trusted_without_changing_confidence(
    db_session: Session,
) -> None:
    graph = GraphBuilder(db_session)
    fact = graph.entity("BrakeController", confidence="0.850")
    review = reviewer(db_session, graph)

    result = review.verify_entity(fact.id, "Evidence confirmed")

    assert result.trust_state is TrustState.TRUSTED
    assert result.validation_state is ValidationState.HUMAN_VERIFIED
    assert result.confidence == Decimal("0.850")
    assert [i.state for i in review.entity_validation_history(fact.id)] == [
        ValidationState.HUMAN_VERIFIED
    ]
    assert [e.action for e in review.audit_history(fact.id)] == [
        "REVIEW_HUMAN_VERIFIED"
    ]


def test_rejection_leaves_the_queue_and_cannot_be_repeated(db_session: Session) -> None:
    graph = GraphBuilder(db_session)
    fact = graph.entity("BrakeController")
    review = reviewer(db_session, graph, MembershipRole.ADMIN)
    assert len(review.review_queue()) == 1

    rejected = review.reject_entity(fact.id, "Not supported by source")

    assert rejected.validation_state is ValidationState.REJECTED
    assert rejected.trust_state is TrustState.CANDIDATE
    assert review.review_queue() == []
    assert (
        review.entity_validation_history(fact.id)[0].reason == "Not supported by source"
    )
    with pytest.raises(ConflictError, match="already reviewed"):
        review.reject_entity(fact.id, "again")
    with pytest.raises(NotFoundError):
        review.verify_entity(uuid4())


@pytest.mark.parametrize("role", [MembershipRole.VIEWER, MembershipRole.ENGINEER])
def test_non_reviewers_cannot_change_candidates(
    db_session: Session, role: MembershipRole
) -> None:
    graph = GraphBuilder(db_session)
    fact = graph.entity("BrakeController")
    with pytest.raises(ReviewPermissionError):
        reviewer(db_session, graph, role).verify_entity(fact.id)


def test_a_reviewer_cannot_touch_another_projects_facts(db_session: Session) -> None:
    graph, other = GraphBuilder(db_session, "a"), GraphBuilder(db_session, "b")
    foreign = other.entity("Foreign")
    with pytest.raises(NotFoundError):
        reviewer(db_session, graph).verify_entity(foreign.id)
    with pytest.raises(ReviewPermissionError):
        ReviewService(
            ReviewRepository(db_session, graph.project_id),
            ReviewActor("x", other.project_id, MembershipRole.REVIEWER),
        )


def test_the_queue_hides_merged_and_replaced_entities_and_names_relationships(
    db_session: Session,
) -> None:
    graph = GraphBuilder(db_session)
    keep, dup = graph.entity("BrakeController"), graph.entity("BrakeCtrl")
    interface = graph.entity("WheelSpeedInterface", "INTERFACE")
    edge(db_session, graph, keep, "REQUIRES", interface)
    apply_merge(db_session, keep, dup, decided_by="HUMAN", actor_id="r")

    queue = reviewer(db_session, graph).review_queue()

    labels = {item.label for item in queue}
    assert "BrakeCtrl [SOFTWARE_COMPONENT]" not in labels
    assert "BrakeController REQUIRES WheelSpeedInterface" in labels  # names, not UUIDs


# -- entity corrections ----------------------------------------------------------------------------
def test_correction_replaces_the_entity_and_preserves_the_original(
    db_session: Session,
) -> None:
    graph = GraphBuilder(db_session)
    original = graph.entity(
        "BrakeCtl", aliases=("BC",), text="`BrakeCtl` is the controller"
    )
    interface = graph.entity("WheelSpeedInterface", "INTERFACE")
    edge_before = edge(db_session, graph, original, "REQUIRES", interface)
    review = reviewer(db_session, graph)

    corrected = review.correct_entity(
        original.id, "BrakeController", "SOFTWARE_COMPONENT", "Official name"
    )
    db_session.flush()

    assert corrected.trust_state is TrustState.TRUSTED
    assert corrected.validation_state is ValidationState.HUMAN_CORRECTED
    assert corrected.normalized_name == "brakecontroller"
    assert corrected.extraction_metadata["corrected_from_entity_id"] == str(original.id)
    # the AI extraction is untouched and points at its replacement
    assert original.canonical_name == "BrakeCtl" and original.raw_confidence == Decimal(
        "0.900"
    )
    assert original.superseded_by_id == corrected.id
    assert original.trust_state is TrustState.CANDIDATE
    # provenance, aliases (including the old name) and edges follow the corrected entity
    evidence = db_session.scalars(
        select(EntityEvidence).where(EntityEvidence.entity_id == corrected.id)
    ).all()
    assert len(evidence) == 1 and "BrakeCtl" in evidence[0].excerpt
    aliases = {
        (a.alias, a.source)
        for a in db_session.scalars(
            select(EntityAlias).where(EntityAlias.entity_id == corrected.id)
        )
    }
    assert aliases == {("BC", "EXPLICIT"), ("BrakeCtl", "HUMAN")}
    db_session.refresh(edge_before)
    assert edge_before.superseded_by_id is not None
    moved = db_session.get(Relationship, edge_before.superseded_by_id)
    assert moved is not None
    assert (moved.source_entity_id, moved.target_entity_id) == (
        corrected.id,
        interface.id,
    )
    assert moved.validation_state is edge_before.validation_state
    assert (
        db_session.scalar(
            select(RelationshipEvidence.id).where(
                RelationshipEvidence.relationship_id == moved.id
            )
        )
        is not None
    )
    assert [i.state for i in review.entity_validation_history(original.id)] == [
        ValidationState.PENDING,  # the build's own check, kept
        ValidationState.HUMAN_CORRECTED,
    ]
    assert len(review.entity_validation_history(corrected.id)) == 1
    assert review.review_queue()[0].label.startswith(
        "WheelSpeedInterface"
    )  # original left the queue


def test_a_statement_using_the_old_name_binds_to_the_corrected_entity(
    db_session: Session,
) -> None:
    graph = GraphBuilder(db_session)
    original = graph.entity("BrakeCtl")
    interface = graph.entity("WheelSpeedInterface", "INTERFACE")
    corrected = reviewer(db_session, graph).correct_entity(
        original.id, "BrakeController", "SOFTWARE_COMPONENT", "Official name"
    )

    graph.candidate(
        "BrakeCtl", "REQUIRES", "WheelSpeedInterface"
    )  # the document still says BrakeCtl
    GraphBuildService().build(db_session, graph.project_id, "builder")

    row = db_session.scalars(select(Relationship)).one()
    assert (row.source_entity_id, row.target_entity_id) == (corrected.id, interface.id)


def test_correction_input_is_validated(db_session: Session) -> None:
    graph = GraphBuilder(db_session)
    original = graph.entity("BrakeCtl")
    graph.entity("BrakeController")  # already exists with the same type
    review = reviewer(db_session, graph)

    with pytest.raises(ValueError, match="Unsupported entity type"):
        review.correct_entity(original.id, "Other", "NOT_A_TYPE", "r")
    with pytest.raises(ValueError, match="needs a name"):
        review.correct_entity(original.id, "  ---  ", "SOFTWARE_COMPONENT", "r")
    with pytest.raises(ValueError, match="changes nothing"):
        review.correct_entity(original.id, "brake_ctl", "SOFTWARE_COMPONENT", "r")
    with pytest.raises(ConflictError, match="already exists") as raised:
        review.correct_entity(
            original.id, "Brake Controller", "SOFTWARE_COMPONENT", "r"
        )
    assert raised.value.status_code == 409
    assert original.superseded_by_id is None  # nothing was half-applied


# -- relationship corrections --------------------------------------------------------------------------
def test_relationship_correction_supersedes_and_is_not_resurrected_by_a_rebuild(
    db_session: Session,
) -> None:
    graph = GraphBuilder(db_session)
    controller = graph.entity("BrakeController")
    interface = graph.entity("WheelSpeedInterface", "INTERFACE")
    original = edge(db_session, graph, controller, "USES", interface)
    review = reviewer(db_session, graph)

    corrected = review.correct_relationship(
        original.id, controller.id, interface.id, "REQUIRES", "It is a hard requirement"
    )
    GraphBuildService().build(db_session, graph.project_id, "builder")
    GraphBuildService().build(db_session, graph.project_id, "builder")

    db_session.refresh(original)
    assert original.superseded_by_id == corrected.id
    active = db_session.scalars(
        select(Relationship).where(Relationship.superseded_by_id.is_(None))
    ).all()
    assert [r.id for r in active] == [
        corrected.id
    ]  # the AI "USES" proposal did not come back
    assert corrected.validation_state is ValidationState.HUMAN_CORRECTED
    assert corrected.attributes["corrected_from_relationship_id"] == str(original.id)
    assert review.review_queue() == [] or all(
        i.fact_kind == "ENTITY" for i in review.review_queue()
    )


def test_relationship_correction_input_is_validated(db_session: Session) -> None:
    graph = GraphBuilder(db_session)
    controller = graph.entity("BrakeController")
    interface = graph.entity("WheelSpeedInterface", "INTERFACE")
    other = graph.entity("ValveInterface", "INTERFACE")
    gone = graph.entity("Gone", "INTERFACE", state=ValidationState.REJECTED)
    original = edge(db_session, graph, controller, "USES", interface)
    existing = edge(db_session, graph, controller, "REQUIRES", other)
    review = reviewer(db_session, graph)
    ids = (original.id, controller.id)

    with pytest.raises(ValueError, match="Unsupported relationship type"):
        review.correct_relationship(*ids, interface.id, "CONTRADICTS", "r")
    with pytest.raises(ValueError, match="two different endpoints"):
        review.correct_relationship(*ids, controller.id, "REQUIRES", "r")
    with pytest.raises(ValueError, match="changes nothing"):
        review.correct_relationship(*ids, interface.id, "USES", "r")
    with pytest.raises(NotFoundError):
        review.correct_relationship(*ids, uuid4(), "REQUIRES", "r")
    with pytest.raises(ConflictError, match="rejected"):
        review.correct_relationship(*ids, gone.id, "REQUIRES", "r")
    with pytest.raises(ConflictError, match="already exists"):
        review.correct_relationship(*ids, other.id, "REQUIRES", "r")
    assert existing.superseded_by_id is None and original.superseded_by_id is None
