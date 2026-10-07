"""Query planning, bounded graph traversal, and hybrid orchestration tests."""

import asyncio
from uuid import uuid4

from app.canonicalization.core import EntityCandidate
from app.core.config import EmbeddingProviderSettings
from app.models.enums import ExtractionType, TrustState, ValidationState
from app.models.schema import Relationship
from app.providers.fake import FakeEmbeddingProvider
from app.retrieval.graph import GraphTraversalService
from app.retrieval.hybrid import HybridRetrievalService
from app.retrieval.planning import QueryIntent, QueryPlanner
from app.retrieval.vector import EmbeddingService, VectorRetrievalService


def run(coroutine: object) -> object:
    return asyncio.run(coroutine)  # type: ignore[arg-type]


def relationship(
    project: object, source: object, target: object, kind: str = "REQUIRES"
) -> Relationship:
    result = Relationship(
        project_id=project,
        source_entity_id=source,
        target_entity_id=target,
        relationship_type=kind,
        trust_state=TrustState.CANDIDATE,
        extraction_type=ExtractionType.EXPLICIT,
        validation_state=ValidationState.PENDING,
        confidence="0.9",
        attributes={},
    )
    result.id = uuid4()
    return result


def test_entity_linking_relationship_and_dependency_plans() -> None:
    project = uuid4()
    controller = EntityCandidate(
        uuid4(), project, "BrakeController", "SOFTWARE_COMPONENT"
    )
    interface = EntityCandidate(uuid4(), project, "WheelSpeedInterface", "INTERFACE")
    planner = QueryPlanner()
    lookup = planner.plan(
        "What does BrakeController provide?", project, [controller, interface]
    )
    dependency = planner.plan(
        "What depends on BrakeController?", project, [controller, interface]
    )

    assert lookup.entity_id == controller.id
    assert lookup.intent is QueryIntent.RELATIONSHIP_LOOKUP
    assert dependency.intent is QueryIntent.DEPENDENCY
    assert dependency.direction == "INCOMING"
    assert dependency.graph_depth == 2


def test_unknown_and_ambiguous_entity_plans_do_not_traverse_graph() -> None:
    project = uuid4()
    first = EntityCandidate(uuid4(), project, "Gateway", "COMPONENT")
    second = EntityCandidate(uuid4(), project, "Gateway", "SOFTWARE_COMPONENT")
    unknown = QueryPlanner().plan("find calibration notes", project, [first, second])
    ambiguous = QueryPlanner().plan("What uses Gateway?", project, [first, second])

    assert unknown.entity_id is None and not unknown.use_graph
    assert ambiguous.entity_id is None and ambiguous.ambiguous_entity_ids == (
        first.id,
        second.id,
    )


def test_bounded_incoming_outgoing_multihop_traversal_and_paths() -> None:
    project, first, second, third = uuid4(), uuid4(), uuid4(), uuid4()
    edges = [
        relationship(project, first, second),
        relationship(project, second, third, "USES"),
    ]
    service = GraphTraversalService()
    outgoing = service.traverse(first, edges, "OUTGOING", depth=2)
    incoming = service.traverse(second, edges, "INCOMING", depth=1)
    limited = service.traverse(first, edges, "OUTGOING", depth=3, node_limit=2)

    assert len(outgoing.relationships) == 2
    assert outgoing.paths[-1].entity_ids == (first, second, third)
    assert incoming.relationships[0].source_entity_id == first
    assert limited.truncated


class EmptyVectorRepository:
    def search(self, *args: object) -> list[object]:
        return []


def test_hybrid_retrieval_combines_empty_vector_result_with_bounded_graph_result() -> (
    None
):
    project, root, target = uuid4(), uuid4(), uuid4()
    plan = QueryPlanner().plan(
        "What uses EngineController?",
        project,
        [EntityCandidate(root, project, "EngineController", "COMPONENT")],
    )
    vector = VectorRetrievalService(
        EmbeddingService(
            FakeEmbeddingProvider(3),
            EmbeddingProviderSettings(
                provider="fake", model="fake-embedding", dimensions=3
            ),
        )
    )
    result = run(
        HybridRetrievalService(vector, GraphTraversalService()).retrieve(
            plan, EmptyVectorRepository(), [relationship(project, root, target, "USES")]
        )
    )

    assert result.vector_hits == ()  # type: ignore[union-attr]
    assert result.graph is not None  # type: ignore[union-attr]
    assert len(result.graph.relationships) == 1  # type: ignore[union-attr]
