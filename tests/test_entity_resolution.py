"""Entity resolution against PostgreSQL: rules, LLM-for-ambiguity-only, guards, audit, undo."""

from __future__ import annotations

import asyncio
import random

import pytest
from app.canonicalization.merge import apply_merge, remember_different, undo_merge
from app.canonicalization.resolution import (
    EntityResolutionService,
    MergeVerdictBatch,
    ResolutionConfig,
    ResolutionResult,
)
from app.models.enums import SourceClassification, ValidationState
from app.models.schema import (
    AuditEvent,
    Entity,
    EntityAlias,
    EntityEvidence,
    EntityMerge,
    MergeDecision,
    Relationship,
    RelationshipEvidence,
)
from app.providers.contracts import (
    CandidateStructuredOutput,
    LLMProvider,
    LLMRequest,
    ProviderTransientError,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.support.fakes import ScriptedLLM
from tests.support.graph import GraphBuilder

pytestmark = pytest.mark.usefixtures("clean_database")


def resolve(
    session: Session,
    graph: GraphBuilder,
    llm: LLMProvider | None,
    **overrides: object,
) -> ResolutionResult:
    config = ResolutionConfig(**overrides)  # type: ignore[arg-type]
    result = asyncio.run(
        EntityResolutionService(llm, config).resolve(
            session, graph.project_id, "tester"
        )
    )
    session.flush()
    return result


def merged_into(session: Session, entity: Entity) -> Entity | None:
    session.refresh(entity)
    return session.get(Entity, entity.merged_into_id) if entity.merged_into_id else None


# -- deterministic rules ------------------------------------------------------------------------
def test_identical_names_of_compatible_types_merge_without_asking_the_model(
    db_session: Session,
) -> None:
    graph = GraphBuilder(db_session)
    first = graph.entity("BrakeController", "COMPONENT")
    second = graph.entity("brake_controller", "SOFTWARE_COMPONENT")
    llm = ScriptedLLM()

    result = resolve(db_session, graph, llm)

    assert result.rule_merges == 1 and result.llm_merges == 0
    assert llm.calls == 0
    survivor = merged_into(db_session, second) or merged_into(db_session, first)
    assert survivor is not None
    record = db_session.scalars(select(EntityMerge)).one()
    assert record.decided_by == "RULE" and record.rule == "EXACT_NAME"
    assert {record.canonical_entity_id, record.merged_entity_id} == {
        first.id,
        second.id,
    }


def test_an_explicit_alias_merges_the_alias_entity_into_its_owner(
    db_session: Session,
) -> None:
    graph = GraphBuilder(db_session)
    owner = graph.entity(
        "BrakeController", aliases=("BrakeCtrl",), text="`BrakeController` main"
    )
    alias_entity = graph.entity("BrakeCtrl", text="`BrakeCtrl` is used in the diagram")
    llm = ScriptedLLM()

    result = resolve(db_session, graph, llm)

    assert result.rule_merges == 1 and llm.calls == 0
    assert merged_into(db_session, alias_entity) is not None
    record = db_session.scalars(select(EntityMerge)).one()
    assert record.decided_by == "ALIAS"
    # the merged entity's evidence is now reachable from the surviving entity
    survivor_id = record.canonical_entity_id
    cited = db_session.scalars(
        select(EntityEvidence).where(EntityEvidence.entity_id == survivor_id)
    ).all()
    assert len(cited) == 2
    # and the merge is audited
    audit = db_session.scalars(
        select(AuditEvent).where(AuditEvent.action == "ENTITY_MERGED")
    )
    assert len(audit.all()) == 1
    assert owner.id == survivor_id or alias_entity.id == survivor_id


def test_version_numbers_and_qualifiers_are_not_merged_and_never_reach_the_model(
    db_session: Session,
) -> None:
    graph = GraphBuilder(db_session)
    for name in (
        "BrakeInterface_V1",
        "BrakeInterface_V2",
        "WheelSpeed_FL",
        "WheelSpeed_FR",
    ):
        graph.entity(name, "INTERFACE")
    llm = ScriptedLLM()

    result = resolve(db_session, graph, llm)

    assert result.merges_applied == 0
    assert result.blocked_by_guard >= 2
    assert llm.judged_pairs == []


def test_a_reviewed_entity_always_survives_and_two_reviewed_ones_are_left_alone(
    db_session: Session,
) -> None:
    graph = GraphBuilder(db_session)
    verified = graph.entity("Abs", "COMPONENT", state=ValidationState.HUMAN_VERIFIED)
    pending = graph.entity("abs", "SOFTWARE_COMPONENT")
    resolve(db_session, graph, ScriptedLLM())
    assert merged_into(db_session, pending).id == verified.id  # type: ignore[union-attr]
    assert verified.validation_state is ValidationState.HUMAN_VERIFIED

    other = GraphBuilder(db_session, "second")
    one = other.entity("Abs", "COMPONENT", state=ValidationState.HUMAN_VERIFIED)
    two = other.entity(
        "abs", "SOFTWARE_COMPONENT", state=ValidationState.HUMAN_CORRECTED
    )
    result = resolve(db_session, other, ScriptedLLM())
    assert result.merges_applied == 0
    assert merged_into(db_session, one) is None and merged_into(db_session, two) is None


# -- LLM only for ambiguous pairs ---------------------------------------------------------------
def test_the_model_is_asked_only_about_ambiguous_pairs_and_the_answer_is_cached(
    db_session: Session,
) -> None:
    graph = GraphBuilder(db_session)
    graph.entity("BrakeController", aliases=("BrakeCtrl",))
    graph.entity("BrakeCtrl")  # decisive: alias
    graph.entity("WheelSpeedSensor", "COMPONENT")
    graph.entity("WheelSpeedSensorFront", "COMPONENT")  # ambiguous
    graph.entity("Totally Different Thing", "COMPONENT")
    llm = ScriptedLLM()

    first = resolve(db_session, graph, llm)
    assert first.llm_pairs_judged == 1 and first.llm_merges == 0
    assert [set(pair) for pair in llm.judged_pairs] == [
        {"WheelSpeedSensor", "WheelSpeedSensorFront"}
    ]
    cached = db_session.scalars(select(MergeDecision)).all()
    assert [(row.decision, row.source) for row in cached] == [("DIFFERENT", "LLM")]

    calls = llm.calls
    second = resolve(db_session, graph, llm)
    assert llm.calls == calls  # nothing asked again
    assert second.llm_pairs_cached == 1 and second.merges_applied == 0


def test_an_llm_same_verdict_merges_and_records_who_decided(
    db_session: Session,
) -> None:
    graph = GraphBuilder(db_session)
    sensor = graph.entity("Wheel Speed Sensor", "COMPONENT")
    short = graph.entity("WSS", "COMPONENT")
    llm = ScriptedLLM()
    llm.same_pairs = {frozenset({"Wheel Speed Sensor", "WSS"})}

    result = resolve(db_session, graph, llm)

    assert result.llm_merges == 1
    record = db_session.scalars(select(EntityMerge)).one()
    assert record.decided_by == "LLM" and record.llm_model == "scripted-llm"
    assert record.prompt_version and record.reason == "scripted verdict"
    assert record.canonical_entity_id == sensor.id  # the descriptive name survives
    assert merged_into(db_session, short) is not None
    aliases = db_session.scalars(
        select(EntityAlias).where(EntityAlias.entity_id == sensor.id)
    ).all()
    assert [(a.alias, a.source) for a in aliases] == [("WSS", "MERGE")]


def test_a_low_confidence_same_verdict_is_not_applied(db_session: Session) -> None:
    graph = GraphBuilder(db_session)
    graph.entity("Wheel Speed Sensor", "COMPONENT")
    graph.entity("WSS", "COMPONENT")
    llm = ScriptedLLM()
    llm.same_pairs = {frozenset({"Wheel Speed Sensor", "WSS"})}
    llm.merge_confidence = 0.6

    result = resolve(db_session, graph, llm)

    assert result.merges_applied == 0
    decision = db_session.scalars(select(MergeDecision)).one()
    assert decision.decision == "UNSURE"


def test_the_llm_pair_budget_defers_the_rest_and_the_next_run_finishes(
    db_session: Session,
) -> None:
    graph = GraphBuilder(db_session)
    for name in ("AlphaSensor", "AlphaSensorFront", "BetaDriver", "BetaDriverMain"):
        graph.entity(name, "COMPONENT")
    llm = ScriptedLLM()

    first = resolve(db_session, graph, llm, max_llm_pairs=1)
    assert first.llm_pairs_judged == 1 and first.llm_pairs_deferred == 1

    second = resolve(db_session, graph, llm, max_llm_pairs=5)
    assert (
        second.llm_pairs_judged == 1
    )  # the deferred pair is judged now, the first is cached
    assert second.llm_pairs_cached == 1


def test_without_a_model_ambiguous_pairs_are_only_flagged(db_session: Session) -> None:
    graph = GraphBuilder(db_session)
    graph.entity("WheelSpeedSensor", "COMPONENT")
    graph.entity("WheelSpeedSensorFront", "COMPONENT")

    result = resolve(db_session, graph, None)

    assert result.merges_applied == 0 and result.llm_pairs_deferred == 1
    assert db_session.scalars(select(MergeDecision)).one().decision == "UNSURE"


class ExplodingLLM(LLMProvider):
    async def generate_structured(  # type: ignore[override]
        self, request: LLMRequest, response_model: type[MergeVerdictBatch]
    ) -> CandidateStructuredOutput[MergeVerdictBatch]:
        raise ProviderTransientError("rate limited")


def test_a_transient_provider_error_propagates_so_the_job_can_retry(
    db_session: Session,
) -> None:
    graph = GraphBuilder(db_session)
    graph.entity("WheelSpeedSensor", "COMPONENT")
    graph.entity("WheelSpeedSensorFront", "COMPONENT")

    with pytest.raises(ProviderTransientError):
        resolve(db_session, graph, ExplodingLLM())


# -- human decisions and transitivity --------------------------------------------------------------
def test_a_human_different_decision_is_never_overridden(db_session: Session) -> None:
    graph = GraphBuilder(db_session)
    owner = graph.entity("BrakeController", aliases=("BrakeCtrl",))
    twin = graph.entity("BrakeCtrl")
    remember_different(db_session, owner, twin, "These are two separate runnables.")
    llm = ScriptedLLM()

    result = resolve(db_session, graph, llm)

    assert result.merges_applied == 0
    assert merged_into(db_session, twin) is None


def test_transitive_merges_respect_a_forbidden_pair(db_session: Session) -> None:
    graph = GraphBuilder(db_session)
    bridge = graph.entity(
        "BrakeInterface",
        "INTERFACE",
        aliases=("BrakeInterface_V1", "BrakeInterface_V2"),
    )
    v1 = graph.entity("BrakeInterface_V1", "INTERFACE")
    v2 = graph.entity("BrakeInterface_V2", "INTERFACE")

    result = resolve(db_session, graph, ScriptedLLM())

    absorbed = [merged_into(db_session, item) for item in (v1, v2)]
    assert (
        sum(item is not None for item in absorbed) == 1
    )  # V1 and V2 never share a group
    assert all(item is None or item.id == bridge.id for item in absorbed)
    assert result.refused_unions == 1
    refused = db_session.scalars(select(MergeDecision)).all()
    assert [(row.decision, row.fingerprint) for row in refused] == [
        ("UNSURE", "blocked")
    ]


def test_resolution_is_independent_of_row_creation_order(db_session: Session) -> None:
    specs = [
        ("BrakeController", "SOFTWARE_COMPONENT", ("BrakeCtrl",)),
        ("BrakeCtrl", "SOFTWARE_COMPONENT", ()),
        ("WheelSpeedSensor", "COMPONENT", ()),
        ("Wheel Speed Sensor", "SOFTWARE_COMPONENT", ()),
        ("BrakeInterface_V1", "INTERFACE", ()),
        ("BrakeInterface_V2", "INTERFACE", ()),
    ]
    outcomes: list[set[frozenset[str]]] = []
    for attempt in range(3):
        graph = GraphBuilder(db_session, f"order-{attempt}")
        shuffled = specs[:]
        random.Random(attempt).shuffle(shuffled)
        for name, kind, aliases in shuffled:
            graph.entity(name, kind, aliases=aliases)
        resolve(db_session, graph, ScriptedLLM())
        merged = {
            frozenset(
                {
                    db_session.get(Entity, m.canonical_entity_id).normalized_name,  # type: ignore[union-attr]
                    db_session.get(Entity, m.merged_entity_id).normalized_name,
                }  # type: ignore[union-attr]
            )
            for m in db_session.scalars(
                select(EntityMerge).where(EntityMerge.project_id == graph.project_id)
            )
        }
        outcomes.append(merged)
    assert outcomes[0] == outcomes[1] == outcomes[2]
    assert frozenset({"brakecontroller", "brakectrl"}) in outcomes[0]
    assert frozenset({"wheelspeedsensor"}) in outcomes[0]  # same name, compatible types


# -- merge mechanics ---------------------------------------------------------------------------------
def test_merging_repoints_relationships_dedupes_twins_and_can_be_undone(
    db_session: Session,
) -> None:
    graph = GraphBuilder(db_session)
    keep = graph.entity("BrakeController")
    dup = graph.entity("BrakeCtrl")
    target = graph.entity("WheelSpeedInterface", "INTERFACE")
    other = graph.entity("ValveInterface", "INTERFACE")

    def edge(
        source: Entity, kind: str, to: Entity, state: ValidationState
    ) -> Relationship:
        row = Relationship(
            project_id=graph.project_id,
            source_entity_id=source.id,
            target_entity_id=to.id,
            relationship_type=kind,
            extraction_type=keep.extraction_type,
            validation_state=state,
            confidence=keep.confidence,
            attributes={},
        )
        db_session.add(row)
        db_session.flush()
        chunk = graph.chunk(f"{source.canonical_name} {kind} {to.canonical_name}")
        db_session.add(
            RelationshipEvidence(
                project_id=graph.project_id,
                relationship_id=row.id,
                chunk_id=chunk.id,
                source_classification=SourceClassification.DIRECT_TEXT,
                excerpt="x",
            )
        )
        db_session.flush()
        return row

    twin_keep = edge(keep, "REQUIRES", target, ValidationState.PENDING)
    twin_dup = edge(
        dup, "REQUIRES", target, ValidationState.HUMAN_VERIFIED
    )  # reviewed: wins
    moved_edge = edge(dup, "PROVIDES", other, ValidationState.PENDING)
    inner = edge(
        keep, "USES", dup, ValidationState.PENDING
    )  # collapses into a self-loop

    record = apply_merge(
        db_session,
        keep,
        dup,
        decided_by="HUMAN",
        actor_id="reviewer",
        reason="same item",
    )

    db_session.refresh(twin_keep)
    db_session.refresh(twin_dup)
    db_session.refresh(moved_edge)
    db_session.refresh(inner)
    assert twin_keep.superseded_by_id == twin_dup.id  # the reviewed twin is kept
    assert twin_dup.source_entity_id == keep.id
    assert moved_edge.source_entity_id == keep.id
    assert "inactive_reason" in inner.attributes and inner.target_entity_id == dup.id
    assert dup.merged_into_id == keep.id

    undo_merge(db_session, record, "reviewer", "Not the same runnable.")
    db_session.flush()
    for row in (twin_keep, twin_dup, moved_edge, inner, dup):
        db_session.refresh(row)
    assert dup.merged_into_id is None
    assert twin_keep.superseded_by_id is None
    assert twin_dup.source_entity_id == dup.id
    assert moved_edge.source_entity_id == dup.id
    assert "inactive_reason" not in inner.attributes
    assert record.undone_at is not None
    decision = db_session.scalars(select(MergeDecision)).one()
    assert (decision.decision, decision.source) == ("DIFFERENT", "HUMAN")

    with pytest.raises(ValueError, match="already undone"):
        undo_merge(db_session, record, "reviewer", "again")


def test_an_undone_merge_is_not_redone_by_the_next_resolution(
    db_session: Session,
) -> None:
    graph = GraphBuilder(db_session)
    graph.entity("BrakeController", aliases=("BrakeCtrl",))
    graph.entity("BrakeCtrl")
    resolve(db_session, graph, ScriptedLLM())
    record = db_session.scalars(select(EntityMerge)).one()

    undo_merge(db_session, record, "reviewer", "wrong")
    again = resolve(db_session, graph, ScriptedLLM())

    assert again.merges_applied == 0


def test_rerunning_resolution_is_a_no_op(db_session: Session) -> None:
    graph = GraphBuilder(db_session)
    graph.entity("BrakeController", aliases=("BrakeCtrl",))
    graph.entity("BrakeCtrl")
    llm = ScriptedLLM()
    assert resolve(db_session, graph, llm).merges_applied == 1
    again = resolve(db_session, graph, llm)
    assert again.merges_applied == 0 and again.pairs_considered == 0
    assert len(db_session.scalars(select(EntityMerge)).all()) == 1
