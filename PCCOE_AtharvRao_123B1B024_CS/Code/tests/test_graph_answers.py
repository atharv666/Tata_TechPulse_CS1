"""Answers that combine graph facts with source passages, end to end through the HTTP API."""

from __future__ import annotations

import json

import pytest
from app.main import app
from fastapi.testclient import TestClient

from tests.support.fakes import installed_fakes
from tests.support.pipeline import drain, real_runner

pytestmark = pytest.mark.integration

ALICE = {"X-User-Id": "alice"}

DOCUMENT = b"""# Brake HLD
Document Version: 1.0.0

## 1 Components
The primary software component is `BrakeController` (also referenced as `BrakeCtrl`).

- `BrakeController` is a `SOFTWARE_COMPONENT` that manages braking.
- `WheelSpeedSensor` is a `SOFTWARE_COMPONENT` that reads wheel rotation speed.
- `VehicleManager` is a `SOFTWARE_COMPONENT` that supervises the vehicle.
- `WheelSpeedInterface` is an `INTERFACE` that carries wheel speed data.
- `BrakeCommandInterface` is an `INTERFACE` that carries the brake request.

## 2 Dependencies
- `BrakeController` `REQUIRES` `WheelSpeedInterface` through input port `P_Wheel_In`.
- `WheelSpeedSensor` `PROVIDES` `WheelSpeedInterface` through output port `P_Sensor_Out`.
- `VehicleManager` `USES` `BrakeController`.
- `BrakeController` `CONSUMES` `BrakeCommandInterface`.

## 3 Functional flow
- `SlipEstimation` is a `FUNCTIONAL_FLOW` that estimates wheel slip.
- `ValveActuation` is a `FUNCTIONAL_FLOW` that drives the valves.
- `SlipEstimation` `PRECEDES` `ValveActuation`.

## 4 Diagnostics
Diagnostic services follow ISO 14229 and the session timeout is 5000 ms.
"""


@pytest.fixture
def api(clean_database):
    with TestClient(app, raise_server_exceptions=False) as client:
        project_id = client.post(
            "/api/v1/projects", json={"name": "graph-answers"}, headers=ALICE
        ).json()["id"]
        client.post(
            f"/api/v1/projects/{project_id}/documents/upload",
            headers=ALICE,
            files={"file": ("Brake_HLD.md", DOCUMENT, "text/markdown")},
        )
        with installed_fakes():
            drain(real_runner())
            yield client, f"/api/v1/projects/{project_id}"


def ask(client: TestClient, base: str, question: str, mode: str = "HYBRID") -> dict:
    response = client.post(
        f"{base}/query", headers=ALICE, json={"query": question, "mode": mode}
    )
    assert response.status_code == 200, response.text
    return response.json()


def statements(answer: dict) -> set[str]:
    return {
        f"{f['source_entity']} {f['relationship_type']} {f['target_entity']}"
        for f in answer["graph_facts"]
    }


def test_graph_mode_answers_a_relationship_question_with_facts_and_their_sources(
    api,
) -> None:
    client, base = api

    answer = ask(client, base, "What does BrakeController require?", "GRAPH")

    assert answer["status"] == "GROUNDED" and answer["mode"] == "GRAPH"
    assert statements(answer) == {"BrakeController REQUIRES WheelSpeedInterface"}
    fact = answer["graph_facts"][0]
    assert (
        fact["extraction_type"] == "EXPLICIT" and fact["validation_state"] == "PENDING"
    )
    assert 0 < fact["confidence"] <= 1 and fact["citation_ids"]
    [claim] = answer["claims"]
    assert claim["text"] == "BrakeController REQUIRES WheelSpeedInterface"
    citation = answer["citations"][0]
    assert (
        citation["document_name"] == "Brake_HLD.md"
        and "2 Dependencies" in citation["section_path"]
    )
    assert (
        "REQUIRES" in citation["excerpt"]
        and citation["citation_id"] in claim["citation_ids"]
    )
    assert any("not yet human-verified" in item for item in answer["limitations"])
    assert "1 graph fact(s)" in answer["confidence_basis"]


def test_direction_is_respected_in_both_ways_of_asking(api) -> None:
    client, base = api
    incoming = ask(client, base, "What requires WheelSpeedInterface?", "GRAPH")
    assert statements(incoming) == {"BrakeController REQUIRES WheelSpeedInterface"}
    wrong_way = ask(client, base, "What does WheelSpeedInterface require?", "GRAPH")
    assert (
        wrong_way["status"] == "INSUFFICIENT_EVIDENCE"
        and wrong_way["graph_facts"] == []
    )
    providers = ask(client, base, "Who provides WheelSpeedInterface?", "GRAPH")
    assert statements(providers) == {"WheelSpeedSensor PROVIDES WheelSpeedInterface"}
    users = ask(client, base, "What does VehicleManager use?", "GRAPH")
    assert statements(users) == {"VehicleManager USES BrakeController"}


def test_an_alias_in_the_question_finds_the_same_facts(api) -> None:
    client, base = api
    answer = ask(client, base, "What does BrakeCtrl require?", "GRAPH")
    assert statements(answer) == {"BrakeController REQUIRES WheelSpeedInterface"}
    plan = answer["retrieval_trace"]["graph"]["plan"]
    assert plan["linked"][0]["method"] == "ALIAS" and plan["direction"] == "OUTGOING"


def test_hybrid_mode_cites_passages_and_attaches_the_structural_facts(api) -> None:
    client, base = api

    answer = ask(client, base, "What does BrakeController require?", "HYBRID")

    assert answer["status"] == "GROUNDED" and answer["mode"] == "HYBRID"
    assert "BrakeController REQUIRES WheelSpeedInterface" in statements(answer)
    assert answer["claims"] and all(c["citation_ids"] for c in answer["claims"])
    cited = {c["citation_id"] for c in answer["citations"]}
    assert all(set(c["citation_ids"]) <= cited for c in answer["claims"])
    assert answer["retrieval_trace"]["graph"]["facts"]


def test_impact_questions_walk_the_dependency_chain_up_to_three_hops(api) -> None:
    client, base = api

    answer = ask(
        client, base, "What could be affected if WheelSpeedInterface changes?", "GRAPH"
    )

    found = statements(answer)
    assert "BrakeController REQUIRES WheelSpeedInterface" in found  # direct dependent
    assert "WheelSpeedSensor PROVIDES WheelSpeedInterface" in found  # its provider
    assert "VehicleManager USES BrakeController" in found  # indirect, two hops
    assert any("2 hops" in claim["text"] for claim in answer["claims"])
    assert {len(path["entity_ids"]) for path in answer["graph_paths"]} == {2, 3}


def test_a_question_without_a_known_entity_falls_back_to_documents_and_says_so(
    api,
) -> None:
    client, base = api

    answer = ask(client, base, "What is the diagnostic session timeout?", "HYBRID")

    assert answer["mode"] == "SOURCE" and answer["graph_facts"] == []
    assert any("No known entity" in item for item in answer["limitations"])
    assert (
        answer["status"] == "GROUNDED"
    )  # the passage about the 5000 ms timeout answers it
    graph_only = ask(client, base, "What is the diagnostic session timeout?", "GRAPH")
    assert graph_only["status"] == "INSUFFICIENT_EVIDENCE"


def test_source_mode_never_touches_the_graph(api) -> None:
    client, base = api
    answer = ask(client, base, "What does BrakeController require?", "SOURCE")
    assert answer["mode"] == "SOURCE" and answer["graph_facts"] == []
    assert "graph" not in answer["retrieval_trace"]


def test_a_relationship_a_reviewer_rejected_is_no_longer_used(api) -> None:
    client, base = api
    edge = client.get(f"{base}/relationships", headers=ALICE).json()["items"]
    target = next(e for e in edge if e["relationship_type"] == "REQUIRES")

    rejected = client.post(
        f"{base}/relationships/{target['id']}/reject",
        headers=ALICE,
        json={"reason": "This dependency was removed in the design review."},
    )
    assert rejected.status_code == 200

    answer = ask(client, base, "What does BrakeController require?", "GRAPH")
    assert answer["status"] == "INSUFFICIENT_EVIDENCE" and answer["graph_facts"] == []


def test_open_findings_about_the_entities_in_an_answer_are_surfaced(api) -> None:
    client, base = api

    answer = ask(client, base, "What does BrakeController consume?", "GRAPH")

    assert statements(answer) == {"BrakeController CONSUMES BrakeCommandInterface"}
    [finding] = answer["related_findings"]
    assert (
        finding["finding_type"] == "MISSING_PROVIDER" and finding["severity"] == "HIGH"
    )
    assert finding["summary"].startswith("Potential inconsistency detected:")
    assert "BrakeCommandInterface" in finding["summary"]
    clean = ask(client, base, "What does VehicleManager use?", "GRAPH")
    assert clean["related_findings"] == []


def test_the_trace_records_decisions_without_the_question_text(api) -> None:
    client, base = api
    question = "What does BrakeController require?"
    answer = ask(client, base, question, "HYBRID")
    assert question not in json.dumps(
        answer["retrieval_trace"]["graph"]
    )  # ids and decisions only
    plan = answer["retrieval_trace"]["graph"]["plan"]
    assert plan["intent"] == "DEPENDENCY" and plan["relationship_types"] == ["REQUIRES"]


def test_functional_flow_order_is_answered_in_both_directions(api) -> None:
    client, base = api
    after = ask(client, base, "What happens after SlipEstimation?", "GRAPH")
    assert statements(after) == {"SlipEstimation PRECEDES ValveActuation"}
    before = ask(client, base, "What happens before ValveActuation?", "GRAPH")
    assert statements(before) == {"SlipEstimation PRECEDES ValveActuation"}
    nothing = ask(client, base, "What happens after ValveActuation?", "GRAPH")
    assert nothing["status"] == "INSUFFICIENT_EVIDENCE"
