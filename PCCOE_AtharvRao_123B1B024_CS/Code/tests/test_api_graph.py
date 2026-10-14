"""Knowledge-graph HTTP API: detail with provenance, findings, merge log and undo."""

from __future__ import annotations

import pytest
from app.main import app
from fastapi.testclient import TestClient

from tests.support.fakes import installed_fakes
from tests.support.pipeline import drain, real_runner

pytestmark = pytest.mark.integration

ALICE = {"X-User-Id": "alice"}
BOB = {"X-User-Id": "bob"}

DOCUMENT = b"""# Brake HLD
Document Version: 1.0.0

## 1 Components
The primary software component is `BrakeController` (also referenced as `BrakeCtrl`).

- `BrakeController` is a `SOFTWARE_COMPONENT` that manages braking.
- `BrakeCtrl` is a `SOFTWARE_COMPONENT` that appears in the wiring diagram.
- `WheelSpeedInterface` is an `INTERFACE` that carries wheel speed data.

## 2 Dependencies
- `BrakeCtrl` `REQUIRES` `WheelSpeedInterface` through input port `P_Wheel_In`.
- `BrakeController` `PART_OF` `ChassisDomain`.
"""


@pytest.fixture
def api(clean_database):
    with TestClient(app, raise_server_exceptions=False) as client:
        project = client.post(
            "/api/v1/projects", json={"name": "graph-api"}, headers=ALICE
        )
        assert project.status_code == 201
        project_id = project.json()["id"]
        client.post(
            f"/api/v1/projects/{project_id}/members",
            json={"user_id": "bob", "role": "VIEWER"},
            headers=ALICE,
        )
        client.post(
            f"/api/v1/projects/{project_id}/documents/upload",
            headers=ALICE,
            files={"file": ("Brake_HLD.md", DOCUMENT, "text/markdown")},
        )
        with installed_fakes():
            drain(real_runner())
        yield client, f"/api/v1/projects/{project_id}"


def items(
    client: TestClient, url: str, headers: dict[str, str] = ALICE, **params: object
):
    response = client.get(url, headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()["items"]


def entity_named(client: TestClient, base: str, name: str) -> dict:
    return next(
        item
        for item in items(client, f"{base}/entities", q=name)
        if item["canonical_name"] == name
    )


def test_entity_lists_show_live_entities_with_status_text_and_alias_search(api) -> None:
    client, base = api
    names = {item["canonical_name"] for item in items(client, f"{base}/entities")}
    assert "BrakeController" in names and "BrakeCtrl" not in names  # merged away
    assert {
        i["canonical_name"] for i in items(client, f"{base}/entities", q="ctrl")
    } == {"BrakeController"}  # found through its alias
    only_interfaces = items(client, f"{base}/entities", entity_type="INTERFACE")
    assert {i["canonical_name"] for i in only_interfaces} == {"WheelSpeedInterface"}
    controller = entity_named(client, base, "BrakeController")
    assert controller["status_text"].endswith("EXPLICIT · PENDING")
    assert controller["status_text"].startswith("Confidence 0.")


def test_pagination_is_stable_and_validated(api) -> None:
    client, base = api
    first = client.get(
        f"{base}/entities", headers=ALICE, params={"limit": 1, "offset": 0}
    ).json()
    second = client.get(
        f"{base}/entities", headers=ALICE, params={"limit": 1, "offset": 1}
    ).json()
    assert first["total"] == second["total"] >= 2
    assert first["items"][0]["id"] != second["items"][0]["id"]
    assert (
        client.get(f"{base}/entities", headers=ALICE, params={"limit": 0}).status_code
        == 422
    )


def test_entity_detail_explains_why_the_fact_exists(api) -> None:
    client, base = api
    controller = entity_named(client, base, "BrakeController")

    detail = client.get(f"{base}/entities/{controller['id']}", headers=ALICE).json()

    assert [a["alias"] for a in detail["aliases"]] == ["BrakeCtrl"]
    assert [m["name"] for m in detail["merged_entities"]] == ["BrakeCtrl"]
    assert detail["merged_entities"][0]["decided_by"] == "ALIAS"
    assert detail["relationship_count"] == 1  # REQUIRES (PART_OF's target is undefined)
    assert detail["evidence"] and all(
        e["excerpt"] and e["document_name"] for e in detail["evidence"]
    )
    assert {e["document_name"] for e in detail["evidence"]} == {"Brake_HLD.md"}
    assert detail["history"][0]["state"] == "PENDING"


def test_relationship_detail_has_endpoints_provenance_and_status(api) -> None:
    client, base = api
    edge = items(client, f"{base}/relationships")[0]

    detail = client.get(f"{base}/relationships/{edge['id']}", headers=ALICE).json()

    assert detail["source"]["name"] == "BrakeController"
    assert detail["target"]["name"] == "WheelSpeedInterface"
    assert detail["relationship_type"] == "REQUIRES"
    assert detail["evidence"][0]["section_heading"].startswith("2 Dependencies")
    assert "REQUIRES" in detail["evidence"][0]["excerpt"]
    assert "EXPLICIT" in detail["status_text"] and "PENDING" in detail["status_text"]
    assert (
        client.get(
            f"{base}/relationships/{edge['source_entity_id']}", headers=ALICE
        ).status_code
        == 404
    )


def test_findings_are_listed_and_only_reviewers_can_dismiss_them(api) -> None:
    client, base = api
    open_findings = items(client, f"{base}/findings", status="OPEN")
    types = {f["finding_type"] for f in open_findings}
    assert {"MISSING_ENTITY_DEFINITION", "MISSING_PROVIDER"} <= types
    assert all(
        f["summary"].startswith("Potential inconsistency detected:")
        for f in open_findings
    )
    target = next(f for f in open_findings if f["finding_type"] == "MISSING_PROVIDER")

    assert (
        client.post(
            f"{base}/findings/{target['id']}/dismiss",
            headers=BOB,
            json={"reason": "Not mine to say"},
        ).status_code
        == 403
    )  # a viewer
    assert (
        client.post(
            f"{base}/findings/{target['id']}/dismiss",
            headers=ALICE,
            json={"reason": ""},
        ).status_code
        == 422
    )
    dismissed = client.post(
        f"{base}/findings/{target['id']}/dismiss",
        headers=ALICE,
        json={"reason": "Provided by the platform layer."},
    )
    assert dismissed.status_code == 200
    assert dismissed.json()["status"] == "DISMISSED"
    assert dismissed.json()["dismissed_by"] == "alice"
    assert target["id"] not in {
        f["id"] for f in items(client, f"{base}/findings", status="OPEN")
    }
    assert (
        client.post(f"{base}/findings/{target['id']}/reopen", headers=ALICE).status_code
        == 200
    )
    assert (
        client.get(
            f"{base}/findings", headers=ALICE, params={"status": "bogus"}
        ).status_code
        == 422
    )
    missing = "00000000-0000-0000-0000-000000000000"
    assert (
        client.post(
            f"{base}/findings/{missing}/dismiss",
            headers=ALICE,
            json={"reason": "whatever"},
        ).status_code
        == 404
    )


def test_the_merge_log_shows_the_decision_and_a_reviewer_can_undo_it(api) -> None:
    client, base = api
    [merge] = items(client, f"{base}/merges")
    assert (merge["canonical_name"], merge["merged_name"]) == (
        "BrakeController",
        "BrakeCtrl",
    )
    assert merge["decided_by"] == "ALIAS" and merge["undone_at"] is None

    assert (
        client.post(
            f"{base}/merges/{merge['id']}/undo",
            headers=BOB,
            json={"reason": "viewer attempt"},
        ).status_code
        == 403
    )
    undone = client.post(
        f"{base}/merges/{merge['id']}/undo",
        headers=ALICE,
        json={"reason": "BrakeCtrl is a separate runnable."},
    )
    assert undone.status_code == 204

    names = {i["canonical_name"] for i in items(client, f"{base}/entities")}
    assert {"BrakeController", "BrakeCtrl"} <= names  # both are live again
    [after] = items(client, f"{base}/merges")
    assert after["undone_at"] and after["undone_by"] == "alice"
    assert items(client, f"{base}/merges", include_undone=False) == []
    again = client.post(
        f"{base}/merges/{merge['id']}/undo", headers=ALICE, json={"reason": "once more"}
    )
    assert again.status_code == 409 and again.json()["code"] == "MERGE_NOT_UNDOABLE"
    audit_actions = {a["action"] for a in items(client, f"{base}/audit")}
    assert {"ENTITY_MERGED", "ENTITY_MERGE_UNDONE"} <= audit_actions


def test_a_manual_rebuild_does_not_redo_an_undone_merge(api) -> None:
    client, base = api
    [merge] = items(client, f"{base}/merges")
    client.post(
        f"{base}/merges/{merge['id']}/undo", headers=ALICE, json={"reason": "Different"}
    )

    job = client.post(f"{base}/graph-build", headers=ALICE)
    assert job.status_code == 202
    with installed_fakes():
        drain(real_runner())

    entities = {i["canonical_name"] for i in items(client, f"{base}/entities")}
    assert "BrakeCtrl" in entities
    assert len(items(client, f"{base}/merges")) == 1  # nothing new was merged


def test_members_and_audit_serialise_and_members_are_admin_only(api) -> None:
    client, base = api
    members = items(client, f"{base}/members")
    assert {(m["user_id"], m["role"]) for m in members} == {
        ("alice", "ADMIN"),
        ("bob", "VIEWER"),
    }
    assert client.get(f"{base}/members", headers=BOB).status_code == 403
    added = client.post(
        f"{base}/members", headers=ALICE, json={"user_id": "carol", "role": "REVIEWER"}
    )
    assert added.status_code == 201 and added.json() == {
        "user_id": "carol",
        "role": "REVIEWER",
    }
    events = items(client, f"{base}/audit")
    assert events and {"action", "actor_id", "resource_type", "created_at"} <= set(
        events[0]
    )
