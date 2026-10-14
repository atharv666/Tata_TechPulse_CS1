"""Conservative entity and relationship canonicalization tests."""

import asyncio
from uuid import uuid4

from app.canonicalization.core import (
    EntityCandidate,
    EntityResolver,
    ResolutionState,
    UnionFind,
    canonical_relationship_type,
    normalize_name,
    normalize_type,
)
from app.providers.fake import FakeLLMProvider


def run(coroutine: object) -> object:
    return asyncio.run(coroutine)  # type: ignore[arg-type]


def candidate(
    project_id: object,
    name: str,
    entity_type: str = "SOFTWARE_COMPONENT",
    aliases: tuple[str, ...] = (),
) -> EntityCandidate:
    return EntityCandidate(
        id=uuid4(),
        project_id=project_id,
        canonical_name=name,
        entity_type=entity_type,
        aliases=aliases,
    )


def test_exact_case_spacing_and_type_normalization() -> None:
    project = uuid4()
    item = candidate(project, "Brake Controller")
    resolution = EntityResolver().resolve(project, "brake_controller", "SWC", [item])
    assert resolution.state is ResolutionState.EXACT
    assert resolution.entity_id == item.id
    assert normalize_name("Brake-Ctrl") == "brakectrl"
    assert normalize_type("software component") == "SOFTWARE_COMPONENT"


def test_alias_match_and_cross_project_separation() -> None:
    project, other = uuid4(), uuid4()
    item = candidate(project, "BrakeController", aliases=("Brake Ctrl",))
    foreign = candidate(other, "Brake Ctrl", aliases=("Brake Controller",))
    resolution = EntityResolver().resolve(
        project, "Brake Ctrl", "SOFTWARE_COMPONENT", [item, foreign]
    )
    assert resolution.state is ResolutionState.ALIAS
    assert resolution.entity_id == item.id


def test_similar_names_remain_ambiguous_or_unresolved_not_silently_merged() -> None:
    project = uuid4()
    first, second = (
        candidate(project, "VehicleStatusController"),
        candidate(project, "VehicleStateController"),
    )
    resolution = EntityResolver(merge_threshold=0.99, ambiguity_threshold=0.7).resolve(
        project, "VehicleStatController", "SOFTWARE_COMPONENT", [first, second]
    )
    assert resolution.state is ResolutionState.AMBIGUOUS
    assert set(resolution.candidates) == {first.id, second.id}


def test_clear_duplicate_merges_and_union_find_groups_transitively() -> None:
    project = uuid4()
    item = candidate(project, "BrakeController")
    resolution = EntityResolver().resolve(
        project, "Brake Controller", "SOFTWARE_COMPONENT", [item]
    )
    assert resolution.state is ResolutionState.EXACT
    union_find = UnionFind()
    first, second, third = uuid4(), uuid4(), uuid4()
    union_find.union(first, second)
    union_find.union(second, third)
    assert union_find.groups() == [{first, second, third}]


def test_llm_is_used_only_for_ambiguous_existing_candidates_and_cannot_invent_entity() -> (
    None
):
    project = uuid4()
    first, second = (
        candidate(project, "EngineController"),
        candidate(project, "EngineControl"),
    )
    resolver = EntityResolver(merge_threshold=0.99, ambiguity_threshold=0.5)
    ambiguous = resolver.resolve(
        project, "EngineControll", "SOFTWARE_COMPONENT", [first, second]
    )
    selected = run(
        resolver.resolve_ambiguity_with_llm(
            FakeLLMProvider(
                {"is_same_entity": True, "selected_entity_id": str(uuid4())}
            ),
            "EngineControll",
            ambiguous,
            [first, second],
        )
    )
    assert selected.state is ResolutionState.AMBIGUOUS  # type: ignore[union-attr]


def test_relationship_type_canonicalization_is_conservative() -> None:
    assert canonical_relationship_type("uses") == "USES"
    assert canonical_relationship_type("UTILIZES") == "USES"
    assert canonical_relationship_type("implemented by") == "IMPLEMENTED_BY"
    assert canonical_relationship_type("contradicts") is None
