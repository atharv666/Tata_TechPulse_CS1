"""Pure-logic tests for entity resolution: names, blocking, scoring, guards, Union-Find."""

from __future__ import annotations

from uuid import UUID, uuid4

from app.canonicalization.blocking import blocking_keys, candidate_pairs
from app.canonicalization.guards import group_conflict, guard_reason
from app.canonicalization.names import (
    acronym,
    core_tokens,
    looks_like_acronym,
    number_tokens,
    opposite_qualifier,
    tokenize,
)
from app.canonicalization.resolution import choose_survivor
from app.canonicalization.scoring import score_pair
from app.canonicalization.union import ConstrainedUnionFind
from app.canonicalization.view import EntityView, pair_key


def view(
    name: str,
    entity_type: str = "SOFTWARE_COMPONENT",
    aliases: tuple[str, ...] = (),
    state: str = "PENDING",
    evidence: int = 1,
    rank: int = 0,
) -> EntityView:
    return EntityView(uuid4(), name, entity_type, aliases, state, evidence, rank)


# -- names -----------------------------------------------------------------------------------
def test_tokenize_handles_camel_snake_digits_and_acronym_runs() -> None:
    assert tokenize("ABSController") == ["abs", "controller"]
    assert tokenize("WheelSpeed_FL") == ["wheel", "speed", "fl"]
    assert tokenize("HTTPServer2") == ["http", "server", "2"]
    assert tokenize("P_WheelSpeed_In") == ["p", "wheel", "speed", "in"]


def test_core_tokens_drop_type_noise_and_numbers() -> None:
    assert core_tokens("BrakeControllerSWC") == ["brake", "controller"]
    assert core_tokens("Port2_Interface") == []
    assert number_tokens("BrakeInterface_V2_3") == ("2", "3")


def test_acronym_helpers() -> None:
    assert acronym("Wheel Speed Sensor") == "wss"
    assert acronym("Sensor") is None
    assert looks_like_acronym("WSS") and looks_like_acronym("ECU")
    assert not looks_like_acronym("WheelSpeed") and not looks_like_acronym("A")


def test_opposite_qualifiers_are_detected_only_when_they_swap() -> None:
    assert opposite_qualifier("WheelSpeed_FL", "WheelSpeed_FR")
    assert opposite_qualifier("BrakeRequest", "BrakeResponse")
    assert not opposite_qualifier("WheelSpeed_FL", "WheelSpeed_FL_Raw")
    assert not opposite_qualifier("BrakeController", "BrakeControllerSWC")


# -- scoring -----------------------------------------------------------------------------------
def test_identical_normalized_names_are_decisive() -> None:
    score = score_pair(view("Brake Controller"), view("brake_controller"))
    assert score.decisive == "EXACT_NAME" and score.similarity == 1.0


def test_an_alias_match_is_decisive_but_distinguished() -> None:
    score = score_pair(
        view("BrakeController", aliases=("BrakeCtrl",)), view("BrakeCtrl")
    )
    assert score.decisive == "ALIAS"


def test_similar_names_are_never_decisive() -> None:
    for left, right in (
        ("WheelSpeedSensor", "WheelSpeedSensorFront"),
        ("Wheel Speed Sensor", "WSS"),
        ("BrakeController", "BrakeControllerV2"),
    ):
        assert score_pair(view(left), view(right)).decisive is None


def test_extension_and_acronym_raise_the_score_into_the_judging_band() -> None:
    assert (
        score_pair(view("WheelSpeedSensor"), view("WheelSpeedSensorFront")).similarity
        >= 0.75
    )
    assert score_pair(view("Wheel Speed Sensor"), view("WSS")).similarity >= 0.8
    assert score_pair(view("BrakeController"), view("EngineTimer")).similarity < 0.5


# -- blocking ----------------------------------------------------------------------------------
def test_blocking_keys_are_scoped_by_type_group() -> None:
    component = view("BrakeController", "COMPONENT")
    software = view("BrakeController", "SOFTWARE_COMPONENT")
    interface = view("BrakeController", "INTERFACE")
    assert blocking_keys(component) == blocking_keys(software)
    assert not blocking_keys(component) & blocking_keys(interface)


def test_blocking_proposes_alias_and_acronym_pairs_but_not_unrelated_ones() -> None:
    sensor = view("Wheel Speed Sensor", "COMPONENT")
    acronym_form = view("WSS", "COMPONENT")
    unrelated = view("DiagnosticLogger", "COMPONENT")
    pairs = candidate_pairs([sensor, acronym_form, unrelated]).pairs
    keys = {frozenset(pair) for pair in pairs}
    assert frozenset({sensor.id, acronym_form.id}) in keys
    assert not any(unrelated.id in pair for pair in pairs)


def test_oversized_blocks_are_skipped_instead_of_exploding() -> None:
    members = [view(f"Wheel{index}Unit", "COMPONENT") for index in range(60)]
    result = candidate_pairs(members, max_block_size=10)
    assert result.skipped_blocks >= 1
    assert len(result.pairs) < 60 * 59 // 2


def test_blocking_output_is_order_independent() -> None:
    items = [
        view("BrakeController"),
        view("BrakeCtrl", aliases=("BrakeController",)),
        view("X"),
    ]
    forward = candidate_pairs(items).pairs
    backward = candidate_pairs(list(reversed(items))).pairs
    assert forward == backward


# -- guards ------------------------------------------------------------------------------------
def test_version_and_index_numbers_block_a_merge() -> None:
    assert (
        guard_reason(view("BrakeInterface_V1"), view("BrakeInterface_V2")) is not None
    )
    assert guard_reason(view("Port1"), view("Port2")) is not None
    assert guard_reason(view("BrakeInterface"), view("BrakeInterface_V2")) is not None


def test_opposite_qualifiers_and_types_block_a_merge() -> None:
    assert guard_reason(view("WheelSpeed_FL"), view("WheelSpeed_FR")) is not None
    assert guard_reason(view("BrakeStatus", "INTERFACE"), view("BrakeStatus", "SIGNAL"))


def test_component_and_software_component_may_describe_one_item() -> None:
    assert (
        guard_reason(view("Abs", "COMPONENT"), view("Abs", "SOFTWARE_COMPONENT"))
        is None
    )


def test_two_human_reviewed_entities_are_never_merged_automatically() -> None:
    reviewed = {"state": "HUMAN_VERIFIED"}
    reason = guard_reason(view("A", **reviewed), view("A", **reviewed))
    assert reason is not None and "human" in reason


def test_recorded_must_not_link_pair_is_respected() -> None:
    first, second = (
        view("BrakeController"),
        view("BrakeCtrl", aliases=("BrakeController",)),
    )
    assert guard_reason(first, second) is None
    blocked = frozenset({pair_key(first.id, second.id)})
    assert guard_reason(first, second, blocked) is not None


def test_a_shared_name_bypasses_digit_checks() -> None:
    first = view("Port1")
    second = view("P1", aliases=("Port1",))
    assert guard_reason(first, second) is None


# -- constrained union-find -----------------------------------------------------------------------
def make_union(items: list[EntityView]) -> ConstrainedUnionFind:
    by_id = {item.id: item for item in items}

    def check(left: list[UUID], right: list[UUID]) -> tuple[UUID, UUID, str] | None:
        return group_conflict([by_id[i] for i in left], [by_id[i] for i in right])

    return ConstrainedUnionFind(check)


def test_transitive_merging_groups_compatible_items() -> None:
    a, b, c = view("WSS"), view("Wheel Speed Sensor"), view("WheelSpeedSensor")
    union = make_union([a, b, c])
    assert union.union(a.id, b.id)
    assert union.union(b.id, c.id)
    assert [set(group) for group in union.groups()] == [{a.id, b.id, c.id}]


def test_a_union_that_would_join_forbidden_members_is_refused() -> None:
    v1, v2 = view("BrakeInterface_V1"), view("BrakeInterface_V2")
    bridge = view("BrakeInterface", aliases=("BrakeInterface_V1", "BrakeInterface_V2"))
    union = make_union([v1, v2, bridge])
    assert union.union(v1.id, bridge.id)
    assert not union.union(v2.id, bridge.id)  # would put V1 and V2 in one group
    assert len(union.refused) == 1 and "numbers" in union.refused[0].reason
    assert [set(group) for group in union.groups()] == [{v1.id, bridge.id}]


def test_union_result_does_not_depend_on_the_order_of_pairs() -> None:
    items = [view(name) for name in ("Alpha", "Alpha2", "AlphaCtrl", "AlphaController")]
    pairs = [(0, 2), (2, 3), (0, 1), (1, 3)]  # Alpha2 must stay apart from the rest

    def outcome(order: list[tuple[int, int]]) -> list[set[str]]:
        names = {item.id: item.name for item in items}
        union = make_union(items)
        for first, second in order:
            union.union(items[first].id, items[second].id)
        return sorted(sorted(names[i] for i in group) for group in union.groups())  # type: ignore[misc]

    forward = outcome(pairs)
    assert forward == outcome(list(reversed(pairs)))
    assert all("Alpha2" not in group or len(group) == 1 for group in forward)


# -- survivor ----------------------------------------------------------------------------------
def test_survivor_prefers_reviewed_then_descriptive_then_well_evidenced() -> None:
    acronym_form = view("WSS", evidence=9, rank=0)
    descriptive = view("WheelSpeedSensor", evidence=1, rank=5)
    reviewed = view("Wss", state="HUMAN_VERIFIED", evidence=0, rank=9)
    assert choose_survivor([acronym_form, descriptive]).id == descriptive.id
    assert choose_survivor([acronym_form, descriptive, reviewed]).id == reviewed.id
    first, second = (
        view("Alpha", evidence=3, rank=1),
        view("AlphaX", evidence=5, rank=0),
    )
    assert choose_survivor([first, second]).id == second.id


def test_survivor_is_the_entity_the_document_gave_aliases_to() -> None:
    owner = view("BrakeController", aliases=("BrakeCtrl",), evidence=1, rank=9)
    alias_entity = view("BrakeCtrlEntity", evidence=1, rank=0)
    assert choose_survivor([alias_entity, owner]).id == owner.id
