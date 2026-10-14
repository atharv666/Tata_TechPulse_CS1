"""The knowledge graph built through the real worker path: aliases, merges, binding, findings."""

from __future__ import annotations

import pytest
from app.api.dependencies import CurrentUser
from app.db.session import get_session_factory
from app.models.schema import (
    Entity,
    EntityAlias,
    EntityMerge,
    Finding,
    Job,
    Relationship,
    RelationshipCandidate,
    ValidationEvent,
)
from app.services.api import MvpApiService
from sqlalchemy import func, select

from tests.support.fakes import installed_fakes
from tests.support.pipeline import (
    all_completed,
    create_project,
    drain,
    real_runner,
    states,
    upload,
)

pytestmark = pytest.mark.integration

DOCUMENT = b"""# Brake HLD
Document Version: 1.0.0

## 1 Components
The primary software component is `BrakeController` (also referenced as `BrakeCtrl`).

- `BrakeController` is a `SOFTWARE_COMPONENT` that manages braking.
- `BrakeCtrl` is a `SOFTWARE_COMPONENT` that appears in the wiring diagram.
- `WheelSpeedInterface` is an `INTERFACE` that carries wheel speed data.
- `BrakeInterface_V1` is an `INTERFACE` that carries the legacy brake command.
- `BrakeInterface_V2` is an `INTERFACE` that carries the new brake command.

## 2 Dependencies
- `BrakeCtrl` `REQUIRES` `WheelSpeedInterface` through input port `P_Wheel_In`.
- `BrakeController` `PROVIDES` `BrakeInterface_V2`.
- `BrakeController` `PART_OF` `ChassisDomain`.
"""


def run_pipeline() -> object:
    access = create_project()
    upload(access, "Brake_HLD.md", DOCUMENT)
    with installed_fakes() as (llm, _embedders):
        results = drain(real_runner())
    assert all_completed(results), states(results)
    return access, llm


def test_an_alias_is_merged_and_its_statements_attach_to_the_owner(
    clean_database,
) -> None:
    run_pipeline()

    with get_session_factory()() as session:
        entities = {e.canonical_name: e for e in session.scalars(select(Entity))}
        owner, alias = entities["BrakeController"], entities["BrakeCtrl"]
        assert alias.merged_into_id == owner.id and owner.merged_into_id is None
        record = session.scalars(select(EntityMerge)).one()
        assert record.decided_by == "ALIAS" and record.canonical_entity_id == owner.id
        # the alias entity's own evidence is reachable from the owner
        assert "BrakeCtrl" in {
            item.alias
            for item in session.scalars(select(EntityAlias))
            if item.entity_id == owner.id
        }
        # `BrakeCtrl REQUIRES WheelSpeedInterface` became an edge of the canonical entity
        triples = {
            (
                session.get(Entity, r.source_entity_id).canonical_name,  # type: ignore[union-attr]
                r.relationship_type,
                session.get(Entity, r.target_entity_id).canonical_name,  # type: ignore[union-attr]
            )
            for r in session.scalars(select(Relationship))
        }
    assert ("BrakeController", "REQUIRES", "WheelSpeedInterface") in triples
    assert ("BrakeController", "PROVIDES", "BrakeInterface_V2") in triples


def test_versioned_interfaces_stay_distinct_and_the_model_is_not_consulted(
    clean_database,
) -> None:
    _, llm = run_pipeline()

    with get_session_factory()() as session:
        active = {
            e.canonical_name
            for e in session.scalars(
                select(Entity).where(Entity.merged_into_id.is_(None))
            )
        }
    assert {"BrakeInterface_V1", "BrakeInterface_V2"} <= active
    assert llm.judged_pairs == []  # type: ignore[attr-defined]


def test_unbound_statements_and_missing_providers_become_findings(
    clean_database,
) -> None:
    run_pipeline()

    with get_session_factory()() as session:
        findings = list(session.scalars(select(Finding)))
        by_type: dict[str, list[Finding]] = {}
        for item in findings:
            by_type.setdefault(item.finding_type, []).append(item)
        assert all(
            item.summary.startswith("Potential inconsistency detected:")
            for item in findings
        )
        missing = by_type["MISSING_ENTITY_DEFINITION"]
        assert any("ChassisDomain" in item.summary for item in missing)
        providers = " ".join(item.summary for item in by_type["MISSING_PROVIDER"])
        assert "WheelSpeedInterface" in providers and "BrakeInterface_V1" in providers
        assert "BrakeInterface_V2" not in providers  # BrakeController provides it
        unbound = session.scalars(
            select(RelationshipCandidate).where(
                RelationshipCandidate.status == "UNBOUND"
            )
        ).all()
        assert [c.target_name for c in unbound] == ["ChassisDomain"]


def test_a_manual_rebuild_is_idempotent(clean_database) -> None:
    access, _ = run_pipeline()  # type: ignore[misc]

    def counts() -> tuple[object, ...]:
        with get_session_factory()() as session:
            totals = tuple(
                session.scalar(select(func.count()).select_from(model))
                for model in (
                    Entity,
                    Relationship,
                    EntityMerge,
                    Finding,
                    ValidationEvent,
                    RelationshipCandidate,
                )
            )
            confidences = sorted(
                str(c) for c in session.scalars(select(Relationship.confidence))
            )
        return (*totals, confidences)

    before = counts()
    with get_session_factory()() as session:
        job = MvpApiService(session, CurrentUser(access.user_id)).graph_build(access)  # type: ignore[attr-defined]
        job_id = job.id
        session.commit()
    with installed_fakes() as (llm, _embedders):
        results = drain(real_runner())

    assert states(results) == [("GRAPH_BUILD", "COMPLETED")]
    assert counts() == before
    assert llm.judged_pairs == []  # type: ignore[attr-defined]
    with get_session_factory()() as session:
        details = session.get(Job, job_id).details  # type: ignore[union-attr]
    assert details["build"]["findings_opened"] == 0
    assert details["resolution"]["rule_merges"] == 0
