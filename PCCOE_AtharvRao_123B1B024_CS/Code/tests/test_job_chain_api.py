"""The jobs API exposes what the UI needs to show every processing stage of an upload."""

from __future__ import annotations

import pytest
from app.main import app
from fastapi.testclient import TestClient

from tests.support.fakes import installed_fakes
from tests.support.pipeline import V1, drain, real_runner

pytestmark = pytest.mark.integration
ALICE = {"X-User-Id": "alice"}
EXPECTED = [
    "DOCUMENT_INGESTION",
    "EMBEDDING",
    "GRAPH_EXTRACTION",
    "ENTITY_RESOLUTION",
    "GRAPH_BUILD",
]


def test_the_chain_can_be_followed_from_the_upload_job_to_the_graph_build(
    clean_database,
) -> None:
    with TestClient(app, raise_server_exceptions=False) as client:
        project = client.post(
            "/api/v1/projects", json={"name": "chain"}, headers=ALICE
        ).json()["id"]
        base = f"/api/v1/projects/{project}"
        first = client.post(
            f"{base}/documents/upload",
            headers=ALICE,
            files={"file": ("A.md", V1.read_bytes(), "text/markdown")},
        ).json()
        assert first["job_type"] == "DOCUMENT_INGESTION" and first["created_at"]
        with installed_fakes():
            drain(real_runner())

        jobs = {
            j["id"]: j
            for j in client.get(
                f"{base}/jobs", headers=ALICE, params={"limit": 100}
            ).json()["items"]
        }
        walked, current = [], jobs[first["id"]]
        while current:
            walked.append(current["job_type"])
            current = jobs.get(current["details"].get("next_job_id", ""))
        assert walked == EXPECTED
        assert all(
            j["state"] == "COMPLETED" and j["details"]["progress"] > 0
            for j in jobs.values()
        )
