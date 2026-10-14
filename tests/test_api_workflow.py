"""The system through its HTTP API, with the real worker loop in between (no mocks of our own code)."""

from __future__ import annotations

import pytest
from app.main import app
from fastapi.testclient import TestClient

from tests.support.fakes import installed_fakes
from tests.support.pipeline import V1, V2, drain, real_runner

pytestmark = pytest.mark.integration

ALICE = {"X-User-Id": "alice"}


@pytest.fixture
def client(clean_database):
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def make_project(client: TestClient, name: str = "http-flow") -> str:
    response = client.post("/api/v1/projects", json={"name": name}, headers=ALICE)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def upload(client: TestClient, project: str, name: str, content: bytes):
    return client.post(
        f"/api/v1/projects/{project}/documents/upload",
        headers=ALICE,
        files={"file": (name, content, "text/markdown")},
    )


def test_upload_returns_a_job_and_the_worker_chain_makes_the_document_queryable(
    client,
) -> None:
    project = make_project(client)

    response = upload(client, project, "BrakeController_HLD.md", V1.read_bytes())
    assert (
        response.status_code == 202
        and response.json()["job_type"] == "DOCUMENT_INGESTION"
    )
    with installed_fakes():
        results = drain(real_runner())
        assert [r.job_type for r in results][:2] == ["DOCUMENT_INGESTION", "EMBEDDING"]

        jobs = client.get(f"/api/v1/projects/{project}/jobs", headers=ALICE).json()
        assert {j["state"] for j in jobs["items"]} == {"COMPLETED"}
        versions = client.get(
            f"/api/v1/projects/{project}/documents/"
            + client.get(f"/api/v1/projects/{project}/documents", headers=ALICE).json()[
                "items"
            ][0]["id"]
            + "/versions",
            headers=ALICE,
        ).json()
        assert versions["items"][0]["version_number"] == 1

        answer = client.post(
            f"/api/v1/projects/{project}/query",
            json={"query": "What does BrakeController require?", "mode": "SOURCE"},
            headers=ALICE,
        )

    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["status"] in {"GROUNDED", "INSUFFICIENT_EVIDENCE"}
    assert {
        "confidence",
        "confidence_basis",
        "limitations",
        "retrieval_trace",
        "mode",
    } <= set(body)
    if body["status"] == "GROUNDED":
        citation = body["citations"][0]
        assert citation["section_path"] and citation["role"] in {
            "HIT",
            "PARENT_LEAD",
            "NEIGHBOR",
        }
        assert body["claims"][0]["citation_ids"]


def test_query_requires_authentication_and_project_membership(client) -> None:
    project = make_project(client)
    anonymous = client.post(f"/api/v1/projects/{project}/query", json={"query": "x"})
    stranger = client.post(
        f"/api/v1/projects/{project}/query",
        json={"query": "x"},
        headers={"X-User-Id": "mallory"},
    )
    assert anonymous.status_code == 401
    assert stranger.status_code == 403


def test_query_validates_its_input(client) -> None:
    project = make_project(client)
    for payload in (
        {"query": ""},
        {"query": "x", "top_k": 0},
        {"query": "x", "mode": "NOPE"},
    ):
        response = client.post(
            f"/api/v1/projects/{project}/query", json=payload, headers=ALICE
        )
        assert response.status_code == 422


def test_metrics_endpoint_is_not_available_to_anonymous_callers(client) -> None:
    assert client.get("/api/v1/metrics").status_code == 401
    assert client.get("/api/v1/metrics", headers=ALICE).status_code == 200


def test_second_revision_creates_a_new_version_through_the_api(client) -> None:
    project = make_project(client)
    upload(client, project, "HLD.md", V1.read_bytes())
    upload(client, project, "HLD.md", V2.read_bytes())
    with installed_fakes():
        drain(real_runner())
    document = client.get(
        f"/api/v1/projects/{project}/documents", headers=ALICE
    ).json()["items"][0]
    versions = client.get(
        f"/api/v1/projects/{project}/documents/{document['id']}/versions", headers=ALICE
    ).json()
    assert [v["version_number"] for v in versions["items"]] == [1, 2]
