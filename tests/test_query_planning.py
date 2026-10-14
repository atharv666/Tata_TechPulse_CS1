"""Question understanding: the same relationship asked in different grammatical directions."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.retrieval.linking import EntityLinker, LinkedEntity, LinkResult
from app.retrieval.planning import (
    BOTH,
    INCOMING,
    OUTGOING,
    QueryIntent,
    QueryPlanner,
)
from sqlalchemy.orm import Session

from tests.support.graph import GraphBuilder


def linked(query: str, name: str) -> LinkResult:
    start = query.index(name)
    entity = LinkedEntity(
        uuid4(),
        name,
        "SOFTWARE_COMPONENT",
        name,
        "EXACT",
        1.0,
        start,
        start + len(name),
    )
    return LinkResult([entity])


@pytest.mark.parametrize(
    ("question", "name", "direction", "types"),
    [
        (
            "What does BrakeController require?",
            "BrakeController",
            OUTGOING,
            ("REQUIRES",),
        ),
        (
            "What requires WheelSpeedInterface?",
            "WheelSpeedInterface",
            INCOMING,
            ("REQUIRES",),
        ),
        (
            "What is required by BrakeController?",
            "BrakeController",
            OUTGOING,
            ("REQUIRES",),
        ),
        (
            "What is WheelSpeedInterface required by?",
            "WheelSpeedInterface",
            INCOMING,
            ("REQUIRES",),
        ),
        (
            "Which components use WheelSpeedInterface?",
            "WheelSpeedInterface",
            INCOMING,
            ("USES",),
        ),
        (
            "Which interfaces does BrakeController use?",
            "BrakeController",
            OUTGOING,
            ("USES",),
        ),
        (
            "What does BrakeController provide?",
            "BrakeController",
            OUTGOING,
            ("PROVIDES",),
        ),
        (
            "Who provides WheelSpeedInterface?",
            "WheelSpeedInterface",
            INCOMING,
            ("PROVIDES",),
        ),
        (
            "What is WheelSpeedInterface provided by?",
            "WheelSpeedInterface",
            INCOMING,
            ("PROVIDES",),
        ),
        (
            "Which components consume WheelSpeedInterface?",
            "WheelSpeedInterface",
            INCOMING,
            ("CONSUMES",),
        ),
        ("What does ABS_Module consume?", "ABS_Module", OUTGOING, ("CONSUMES",)),
        (
            "What signals does WheelSpeedInterface carry?",
            "WheelSpeedInterface",
            OUTGOING,
            ("CARRIES",),
        ),
        ("What carries WheelSpeedSignal?", "WheelSpeedSignal", INCOMING, ("CARRIES",)),
        ("What is BrakeController part of?", "BrakeController", OUTGOING, ("PART_OF",)),
        ("What is part of BrakeController?", "BrakeController", INCOMING, ("PART_OF",)),
        ("What implements REQ_Brake?", "REQ_Brake", OUTGOING, ("IMPLEMENTED_BY",)),
        (
            "What does BrakeController implement?",
            "BrakeController",
            INCOMING,
            ("IMPLEMENTED_BY",),
        ),
        (
            "Which tests verify BrakeController?",
            "BrakeController",
            OUTGOING,
            ("VERIFIED_BY",),
        ),
        (
            "What does BrakeController trigger?",
            "BrakeController",
            OUTGOING,
            ("TRIGGERS",),
        ),
        ("What triggers BrakeController?", "BrakeController", INCOMING, ("TRIGGERS",)),
        (
            "What happens after SlipEstimation?",
            "SlipEstimation",
            OUTGOING,
            ("PRECEDES",),
        ),
        ("What follows SlipEstimation?", "SlipEstimation", OUTGOING, ("PRECEDES",)),
        (
            "What happens before ValveActuation?",
            "ValveActuation",
            INCOMING,
            ("PRECEDES",),
        ),
        ("What precedes ValveActuation?", "ValveActuation", INCOMING, ("PRECEDES",)),
        (
            "What does SlipEstimation precede?",
            "SlipEstimation",
            OUTGOING,
            ("PRECEDES",),
        ),
        (
            "What is SlipEstimation followed by?",
            "SlipEstimation",
            OUTGOING,
            ("PRECEDES",),
        ),
        (
            "What is ValveActuation preceded by?",
            "ValveActuation",
            INCOMING,
            ("PRECEDES",),
        ),
        (
            "How is BrakeController connected to the bus?",
            "BrakeController",
            BOTH,
            ("CONNECTS_TO",),
        ),
    ],
)
def test_direction_follows_the_grammar_around_the_entity(
    question: str, name: str, direction: str, types: tuple[str, ...]
) -> None:
    plan = QueryPlanner().plan(question, linked(question, name))
    assert plan.use_graph
    assert (plan.direction, plan.relationship_types[:1]) == (direction, types)


def test_a_question_about_an_entity_without_a_relationship_shows_its_neighbours() -> (
    None
):
    q = "Tell me about BrakeController"
    plan = QueryPlanner().plan(q, linked(q, "BrakeController"))
    assert plan.intent is QueryIntent.NEIGHBORHOOD and plan.direction == BOTH
    assert plan.relationship_types == () and plan.use_graph
    assert any("neighbours" in note for note in plan.notes)


def test_dependency_questions_use_the_dependency_family() -> None:
    q = "What does BrakeController depend on?"
    plan = QueryPlanner().plan(q, linked(q, "BrakeController"))
    assert plan.direction == OUTGOING and plan.intent is QueryIntent.DEPENDENCY
    assert set(plan.relationship_types) == {
        "DEPENDS_ON",
        "REQUIRES",
        "USES",
        "CONSUMES",
    }
    q = "What depends on BrakeController?"
    assert QueryPlanner().plan(q, linked(q, "BrakeController")).direction == INCOMING
    q = "What are the dependencies of BrakeController?"
    assert QueryPlanner().plan(q, linked(q, "BrakeController")).direction == OUTGOING
    q = "List the dependents of BrakeController"
    assert QueryPlanner().plan(q, linked(q, "BrakeController")).direction == INCOMING


def test_impact_questions_use_three_hops_and_no_fixed_type() -> None:
    q = "What could be affected if WheelSpeedInterface changes?"
    plan = QueryPlanner().plan(q, linked(q, "WheelSpeedInterface"))
    assert plan.intent is QueryIntent.IMPACT and plan.graph_depth == 3
    assert plan.relationship_types == ()


def test_transitive_wording_deepens_the_walk_within_bounds() -> None:
    q = "What does BrakeController depend on, directly or indirectly?"
    assert QueryPlanner().plan(q, linked(q, "BrakeController")).graph_depth == 2
    q = "What does BrakeController require?"
    assert QueryPlanner().plan(q, linked(q, "BrakeController")).graph_depth == 1


def test_a_question_without_a_known_entity_does_not_use_the_graph() -> None:
    plan = QueryPlanner().plan("What is the diagnostic session timeout?", LinkResult())
    assert not plan.use_graph and plan.intent is QueryIntent.SOURCE_SEARCH


def test_the_plan_description_contains_no_question_text() -> None:
    q = "What does BrakeController require?"
    description = QueryPlanner().plan(q, linked(q, "BrakeController")).describe()
    assert "require?" not in str(description) and description["direction"] == OUTGOING


# -- linking ----------------------------------------------------------------------------------------
@pytest.mark.usefixtures("clean_database")
class TestLinking:
    def test_names_aliases_and_spaced_forms_are_linked(
        self, db_session: Session
    ) -> None:
        graph = GraphBuilder(db_session)
        controller = graph.entity("BrakeController", aliases=("BrakeCtrl",))
        interface = graph.entity("WheelSpeedInterface", "INTERFACE")
        linker = EntityLinker(db_session, graph.project_id)

        by_name = linker.link("What does BrakeController require?")
        by_alias = linker.link("What does brakectrl require?")
        spaced = linker.link("Who provides the wheel speed interface?")

        assert [(e.entity_id, e.method) for e in by_name.entities] == [
            (controller.id, "EXACT")
        ]
        assert [(e.entity_id, e.method) for e in by_alias.entities] == [
            (controller.id, "ALIAS")
        ]
        assert [e.entity_id for e in spaced.entities] == [interface.id]

    def test_the_longest_mention_wins_and_unrelated_words_link_nothing(
        self, db_session: Session
    ) -> None:
        graph = GraphBuilder(db_session)
        graph.entity("Wheel", "COMPONENT")
        full = graph.entity("Wheel Speed Sensor", "COMPONENT")
        linker = EntityLinker(db_session, graph.project_id)
        assert [
            e.entity_id for e in linker.link("Describe the Wheel Speed Sensor").entities
        ] == [full.id]
        assert linker.link("What is the weather today?").entities == []

    def test_a_name_shared_by_two_types_is_flagged_ambiguous(
        self, db_session: Session
    ) -> None:
        graph = GraphBuilder(db_session)
        graph.entity("BrakeStatus", "SIGNAL")
        graph.entity("BrakeStatus", "INTERFACE")
        result = EntityLinker(db_session, graph.project_id).link(
            "Who uses BrakeStatus?"
        )
        assert len(result.entities) == 2 and all(e.ambiguous for e in result.entities)
        assert any("several entities" in note for note in result.notes)

    def test_a_misspelt_identifier_is_linked_with_a_note_but_not_when_unclear(
        self, db_session: Session
    ) -> None:
        graph = GraphBuilder(db_session)
        graph.entity("WheelSpeedInterface", "INTERFACE")
        graph.entity("WheelSpeedInterfaceX", "INTERFACE")
        graph.entity("ValveCommandInterface", "INTERFACE")
        linker = EntityLinker(db_session, graph.project_id)

        close = linker.link("What provides ValveComandInterface?")
        assert [(e.name, e.method) for e in close.entities] == [
            ("ValveCommandInterface", "FUZZY")
        ]
        assert any("was read as" in note for note in close.notes)

        unclear = linker.link("What provides WheelSpeedInterfac?")
        assert unclear.entities == []  # two names are equally close: refuse to guess

    def test_merged_rejected_and_foreign_entities_are_not_linked(
        self, db_session: Session
    ) -> None:
        from app.models.enums import ValidationState

        graph, other = GraphBuilder(db_session, "a"), GraphBuilder(db_session, "b")
        graph.entity("Gone", state=ValidationState.REJECTED)
        other.entity("Foreign")
        linker = EntityLinker(db_session, graph.project_id)
        assert linker.link("Tell me about Gone and Foreign").entities == []

    def test_at_most_three_entities_are_used(self, db_session: Session) -> None:
        graph = GraphBuilder(db_session)
        for name in ("AlphaUnit", "BetaUnit", "GammaUnit", "DeltaUnit"):
            graph.entity(name, "COMPONENT")
        result = EntityLinker(db_session, graph.project_id).link(
            "Compare AlphaUnit BetaUnit GammaUnit DeltaUnit"
        )
        assert len(result.entities) == 3 and any(
            "only the first 3" in n for n in result.notes
        )
