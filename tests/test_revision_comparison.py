"""Comparison of document versions: text, sections, entities and relationships, with evidence."""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.comparison.diff import diff_statements, statements, values_in
from app.comparison.matching import VersionSection, match_sections
from app.comparison.service import RevisionComparisonService
from app.core.errors import NotFoundError
from app.db.session import get_session_factory
from app.main import app
from app.models.schema import DocumentVersion, Job
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from tests.support.fakes import installed_fakes
from tests.support.pipeline import V1, V2, drain, real_runner

ALICE = {"X-User-Id": "alice"}


# -- pure text comparison -----------------------------------------------------------------------
def test_statements_split_rows_items_and_sentences() -> None:
    text = (
        "Intro sentence. Second one.\n- item one\n| A | B |\n| --- | --- |\n| 1 | 2 |"
    )
    assert statements(text) == [
        "Intro sentence.",
        "Second one.",
        "- item one",
        "| A | B |",
        "| 1 | 2 |",
    ]


def test_values_include_units_hex_and_plain_numbers() -> None:
    assert values_in("Runs every 10 ms at 12 V, DID 0xF190, 3 channels") == (
        "10 ms",
        "12 v",
        "0xf190",
        "3",
    )


def test_a_changed_timing_value_is_reported_as_a_value_change() -> None:
    old = "The runnable is executed every 10 ms. The valve is updated every 5 ms."
    new = "The runnable is executed every 20 ms. The valve is updated every 5 ms."

    diff = diff_statements(old, new)

    assert diff.added == [] and diff.removed == [] and diff.reworded == []
    [change] = diff.changed
    assert change.old_values == ("10 ms",) and change.new_values == ("20 ms",)
    assert "10 ms" in change.old_statement and "20 ms" in change.new_statement


def test_added_removed_and_reworded_statements_are_told_apart() -> None:
    old = "Faults are stored. The ECU wakes on CAN activity.\n- Keep the last valid command."
    new = (
        "Faults are stored in non-volatile memory. The ECU wakes on CAN activity.\n"
        "- Release pressure after 50 ms."
    )
    diff = diff_statements(old, new)
    assert diff.reworded == [
        ("Faults are stored.", "Faults are stored in non-volatile memory.")
    ]
    assert diff.removed == ["- Keep the last valid command."]
    assert diff.added == ["- Release pressure after 50 ms."]
    assert diff_statements(old, old).is_empty


def section(
    heading: str, path: str, text: str = "x", ordinal: int = 1
) -> VersionSection:
    return VersionSection(uuid4(), ordinal, heading, path, text, None, None, None)


def test_renumbered_and_renamed_sections_are_still_paired() -> None:
    old = [
        section("1.1 Components", "Doc > 1 Overview > 1.1 Components", ordinal=1),
        section("2 Timing", "Doc > 2 Timing", ordinal=2),
        section("3 Legacy Notes", "Doc > 3 Legacy Notes", ordinal=3),
    ]
    new = [
        section("1.2 Components", "Doc > 1 Overview > 1.2 Components", ordinal=1),
        section(
            "2 Timing and Diagnostics", "Doc > 2 Timing and Diagnostics", ordinal=2
        ),
        section("4 Brand New", "Doc > 4 Brand New", ordinal=3),
    ]
    matched = match_sections(old, new)
    assert {(a.heading, b.heading) for a, b in matched.pairs} == {
        ("1.1 Components", "1.2 Components"),
        ("2 Timing", "2 Timing and Diagnostics"),
    }
    assert [s.heading for s in matched.removed] == ["3 Legacy Notes"]
    assert [s.heading for s in matched.added] == ["4 Brand New"]


# -- the two sample revisions through the real pipeline -------------------------------------------------
@pytest.fixture
def revisions(clean_database):
    """Both HLD revisions ingested as versions 1 and 2 of one document, comparison queued."""
    with TestClient(app, raise_server_exceptions=False) as client:
        project = client.post(
            "/api/v1/projects", json={"name": "revisions"}, headers=ALICE
        )
        project_id = project.json()["id"]
        base = f"/api/v1/projects/{project_id}"
        for content in (V1.read_bytes(), V2.read_bytes()):
            client.post(
                f"{base}/documents/upload",
                headers=ALICE,
                files={"file": ("BrakeController_HLD.md", content, "text/markdown")},
            )
            with installed_fakes():
                drain(real_runner())
        with get_session_factory()() as session:
            versions = list(
                session.scalars(
                    select(DocumentVersion).order_by(DocumentVersion.version_number)
                )
            )
            ids = [v.id for v in versions]
        queued = client.post(
            f"{base}/comparisons",
            headers=ALICE,
            json={"base_version_id": str(ids[0]), "target_version_id": str(ids[1])},
        )
        assert queued.status_code == 202, queued.text
        comparison_id = queued.json()["details"]["payload"]["comparison_id"]
        with installed_fakes():
            results = drain(real_runner())
        yield client, base, comparison_id, ids, results


def findings_of(
    client: TestClient, base: str, comparison_id: str, **params: str
) -> list[dict]:
    collected: list[dict] = []
    offset = 0
    while True:
        page = client.get(
            f"{base}/comparisons/{comparison_id}/findings",
            headers=ALICE,
            params={"offset": offset, "limit": 100, **params},
        ).json()
        collected.extend(item["details"] for item in page["items"])
        offset += 100
        if offset >= page["total"]:
            return collected


def test_one_job_runs_the_comparison_and_the_comparison_completes(revisions) -> None:
    client, base, comparison_id, ids, results = revisions

    assert [(r.job_type, r.state.value) for r in results] == [
        ("REVISION_COMPARISON", "COMPLETED")
    ]
    with get_session_factory()() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(Job)
                .where(Job.job_type == "REVISION_COMPARISON")
            )
            == 1
        )  # the API's job is the only job (a second, orphan row used to be created)
    detail = client.get(f"{base}/comparisons/{comparison_id}", headers=ALICE).json()
    assert detail["state"] == "COMPLETED" and detail["finding_count"] > 5
    assert detail["base_version_id"] == str(ids[0]) and detail[
        "target_version_id"
    ] == str(ids[1])
    assert detail["summary"]["ADDED"] > 0 and detail["summary"]["REMOVED"] > 0
    listed = client.get(f"{base}/comparisons", headers=ALICE).json()
    assert [item["id"] for item in listed["items"]] == [comparison_id]


def test_document_and_section_level_changes_are_reported(revisions) -> None:
    client, base, comparison_id, *_ = revisions
    findings = findings_of(client, base, comparison_id)

    metadata = [f for f in findings if f["scope"] == "DOCUMENT"]
    assert {(f["changes"]["field"], f["changes"]["new"]) for f in metadata} >= {
        ("version", "2.0.0")
    }
    sections = [f for f in findings if f["scope"] == "SECTION"]
    modified = [f for f in sections if f["classification"] == "MODIFIED"]
    assert any("Overview" in f["summary"] for f in modified)
    assert any(
        f["classification"] == "REMOVED" for f in sections
    )  # e.g. the runnables section
    overview = next(f for f in modified if "Overview" in f["summary"])
    assert (
        overview["old_evidence"]["citations"] and overview["new_evidence"]["citations"]
    )
    assert overview["confidence"] == 1.0  # a deterministic text difference


def test_entity_changes_carry_evidence_from_the_version_they_come_from(
    revisions,
) -> None:
    client, base, comparison_id, ids, _ = revisions
    entities = [
        f for f in findings_of(client, base, comparison_id) if f["scope"] == "ENTITY"
    ]

    by_summary = {f["summary"]: f for f in entities}
    removed = by_summary["Entity removed: ESP_Module (SOFTWARE_COMPONENT)."]
    added = by_summary["Entity added: RegenBrakeModule (SOFTWARE_COMPONENT)."]
    assert removed["classification"] == "REMOVED" and removed["severity"] == "HIGH"
    assert removed["old_evidence"]["citations"][0]["document_version_id"] == str(ids[0])
    assert removed["new_evidence"]["citations"] == []
    assert added["new_evidence"]["citations"][0]["document_version_id"] == str(ids[1])
    renamed = next(f for f in entities if f["classification"] == "RENAMED")
    assert "BrakeCommandInterface" in renamed["summary"]
    assert not any(f["classification"] == "UNCHANGED" for f in entities)


def test_relationship_changes_are_paired_and_unpaired_ones_are_added_or_removed(
    revisions,
) -> None:
    client, base, comparison_id, ids, _ = revisions
    edges = [
        f
        for f in findings_of(client, base, comparison_id)
        if f["scope"] == "RELATIONSHIP"
    ]
    kinds = {f["classification"] for f in edges}

    assert {"TARGET_CHANGED", "REMOVED", "ADDED"} <= kinds
    targets_changed = [f for f in edges if f["classification"] == "TARGET_CHANGED"]
    changed = next(f for f in targets_changed if "PROVIDES" in f["summary"])
    assert "BrakeController PROVIDES BrakeCommandInterface" in changed["summary"]
    assert "BrakeCommandInterface_v2" in changed["summary"]
    assert changed["old_evidence"]["citations"][0]["document_version_id"] == str(ids[0])
    assert changed["new_evidence"]["citations"][0]["document_version_id"] == str(ids[1])
    removed = [f["summary"] for f in edges if f["classification"] == "REMOVED"]
    assert "Relationship removed: ESP_Module DEPENDS_ON BrakeController." in removed
    added = [f["summary"] for f in edges if f["classification"] == "ADDED"]
    assert (
        "Relationship added: RegenBrakeModule PROVIDES RegenStatusInterface." in added
    )


def test_high_severity_changes_list_what_might_be_affected(revisions) -> None:
    client, base, comparison_id, *_ = revisions
    edges = [
        f
        for f in findings_of(client, base, comparison_id)
        if f["scope"] == "RELATIONSHIP"
    ]
    changed = next(f for f in edges if f["classification"] == "TARGET_CHANGED")
    names = {i["affected_entity_name"] for i in changed["impacts"]}
    assert names  # at least the elements around the changed relationship
    assert all(i["via"] for i in changed["impacts"])
    assert all(f["classification"] != "ADDED" or not f["impacts"] for f in edges)


def test_findings_can_be_filtered_and_unknown_comparisons_are_404(revisions) -> None:
    client, base, comparison_id, *_ = revisions
    only_added = findings_of(client, base, comparison_id, classification="ADDED")
    assert only_added and {f["classification"] for f in only_added} == {"ADDED"}
    missing = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"{base}/comparisons/{missing}", headers=ALICE).status_code == 404
    assert (
        client.get(f"{base}/comparisons/{missing}/findings", headers=ALICE).status_code
        == 404
    )
    page = client.get(
        f"{base}/comparisons/{comparison_id}/findings", headers=ALICE
    ).json()
    assert {"id", "confidence", "finding_type", "summary", "details"} <= set(
        page["items"][0]
    )


def test_invalid_comparison_requests_are_rejected(revisions) -> None:
    client, base, _, ids, _ = revisions
    same = client.post(
        f"{base}/comparisons",
        headers=ALICE,
        json={"base_version_id": str(ids[0]), "target_version_id": str(ids[0])},
    )
    assert same.status_code == 400 and "distinct" in same.json()["message"]
    unknown = client.post(
        f"{base}/comparisons",
        headers=ALICE,
        json={"base_version_id": str(ids[0]), "target_version_id": str(uuid4())},
    )
    assert unknown.status_code == 400


def test_comparing_a_version_of_another_project_fails_cleanly(clean_database) -> None:
    with get_session_factory()() as session:
        with pytest.raises(NotFoundError):
            RevisionComparisonService(session, uuid4()).compare(uuid4(), uuid4())
