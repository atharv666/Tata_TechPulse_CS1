"""Upload -> ingest -> embed -> extract -> resolve -> build, through the real job runner.

These tests exercise the path the worker process actually takes (production session factory,
separate sessions per stage, commits between stages). They are the tests that were missing when the
ingestion job crashed on every upload.
"""

from __future__ import annotations

from math import ceil

import pytest
from app.core.config import get_settings
from app.db.session import get_engine, get_session_factory
from app.jobs.orchestration import JobRunner
from app.jobs.pipeline import PipelineHandlers
from app.models.enums import JobState
from app.models.schema import (
    Chunk,
    Document,
    DocumentVersion,
    Entity,
    EntityEvidence,
    Job,
    Relationship,
    RelationshipEvidence,
    Section,
)
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from tests.support.fakes import HashedEmbedder, installed_fakes
from tests.support.pipeline import (
    V1,
    V2,
    all_completed,
    create_project,
    drain,
    real_runner,
    states,
    upload,
)

pytestmark = pytest.mark.integration

CHAIN = [
    ("DOCUMENT_INGESTION", "COMPLETED"),
    ("EMBEDDING", "COMPLETED"),
    ("GRAPH_EXTRACTION", "COMPLETED"),
    ("ENTITY_RESOLUTION", "COMPLETED"),
    ("GRAPH_BUILD", "COMPLETED"),
]


def count(model, project_id) -> int:
    with get_session_factory()() as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(model)
                .where(model.project_id == project_id)
            )
            or 0
        )


def test_upload_runs_the_whole_pipeline_through_the_real_worker_path(
    clean_database,
) -> None:
    access = create_project()
    upload(access, "BrakeController_HLD.md", V1.read_bytes())

    with installed_fakes() as (_llm, embedders):
        results = drain(real_runner())

    assert states(results) == CHAIN
    with get_session_factory()() as session:
        version = session.scalar(select(DocumentVersion))
        assert version is not None and version.version_number == 1
        sections = list(session.scalars(select(Section).order_by(Section.ordinal)))
        chunks = list(session.scalars(select(Chunk)))
        # every child row points at a real parent (the original defect inserted NULL here)
        assert sections and all(
            item.document_version_id == version.id for item in sections
        )
        assert chunks and all(item.document_version_id == version.id for item in chunks)
        assert all(item.embedding is not None for item in chunks)
        assert all(item.extracted_at is not None for item in chunks)
        assert session.scalar(select(func.count()).select_from(Entity)) >= 10
    assert embedders[0].texts_seen == len(chunks)  # type: ignore[attr-defined]


def test_hierarchy_path_breadcrumb_and_lexical_text_are_persisted(
    clean_database,
) -> None:
    access = create_project()
    upload(access, "BrakeController_HLD.md", V1.read_bytes())
    with installed_fakes():
        drain(real_runner())

    with get_session_factory()() as session:
        by_id = {item.id: item for item in session.scalars(select(Section))}
        components = next(
            item for item in by_id.values() if item.heading.startswith("1.1")
        )
        parent = by_id[components.parent_section_id]
        grandparent = by_id[parent.parent_section_id]
        assert parent.heading == "1 Subsystem Architecture Overview"
        assert parent.number_label == "1" and components.number_label == "1.1"
        assert grandparent.heading.startswith("AUTOSAR High-Level Design")
        assert components.depth == 3 and grandparent.depth == 1
        assert components.path == (
            f"{grandparent.heading} > 1 Subsystem Architecture Overview"
            " > 1.1 Components and Interfaces"
        )

        chunk = session.scalar(select(Chunk).where(Chunk.section_id == components.id))
        assert chunk is not None
        assert chunk.breadcrumb == f"BrakeController_HLD.md > {components.path}"
        assert chunk.embedding_text == f"{chunk.breadcrumb}\n{chunk.content}"
        assert not chunk.content.startswith("Section:")  # raw text only
        assert "wheelspeedsensor" in chunk.lexical_text.split()
        assert chunk.content_hash and len(chunk.content_hash) == 64
        # the generated tsvector column is populated by PostgreSQL
        matches = session.scalar(
            select(func.count())
            .select_from(Chunk)
            .where(
                Chunk.search_vector.op("@@")(
                    func.to_tsquery("english", "wheelspeedsensor")
                )
            )
        )
        assert matches >= 1


def test_document_properties_record_metadata_and_parse_statistics(
    clean_database,
) -> None:
    access = create_project()
    upload(access, "BrakeController_HLD.md", V1.read_bytes())
    with installed_fakes():
        drain(real_runner())

    with get_session_factory()() as session:
        version = session.scalar(select(DocumentVersion))
        assert version is not None
        assert version.properties["version"] == "1.0.0"
        assert version.properties["classification"] == "Synthetic Technical Fixture"
        assert version.properties["structure_source"] == "markdown"
        assert version.properties["section_count"] >= 7
        assert "document version 1.0.0" in version.source_label


def test_every_fact_has_provenance_back_to_a_chunk(clean_database) -> None:
    access = create_project()
    upload(access, "BrakeController_HLD.md", V1.read_bytes())
    with installed_fakes():
        drain(real_runner())

    with get_session_factory()() as session:
        entities = list(session.scalars(select(Entity)))
        relationships = list(session.scalars(select(Relationship)))
        assert relationships
        for entity in entities:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(EntityEvidence)
                    .where(EntityEvidence.entity_id == entity.id)
                )
                >= 1
            )
        for relationship in relationships:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(RelationshipEvidence)
                    .where(RelationshipEvidence.relationship_id == relationship.id)
                )
                >= 1
            )
        # extracted facts are only ever candidates: nothing is verified by the pipeline
        assert all(
            item.validation_state.value in {"PENDING", "REJECTED"} for item in entities
        )


def test_section_five_dependency_is_extracted_regardless_of_chunk_storage_order(
    clean_database,
) -> None:
    """The dependency in section 5 references entities defined in section 1.1."""
    access = create_project()
    upload(access, "BrakeController_HLD.md", V1.read_bytes())
    with installed_fakes():
        drain(real_runner())

    with get_session_factory()() as session:
        names = {
            item.id: item.canonical_name for item in session.scalars(select(Entity))
        }
        triples = {
            (
                names[item.source_entity_id],
                item.relationship_type,
                names[item.target_entity_id],
            )
            for item in session.scalars(select(Relationship))
        }
    assert ("ESP_Module", "DEPENDS_ON", "BrakeController") in triples
    assert ("BrakeController", "REQUIRES", "WheelSpeedInterface") in triples


def test_embedding_terminates_with_autoflush_disabled(clean_database) -> None:
    """Regression for the unbounded re-embedding loop (app sessions used to have autoflush off)."""
    access = create_project()
    upload(access, "BrakeController_HLD.md", V1.read_bytes())
    no_autoflush = sessionmaker(
        bind=get_engine(), autoflush=False, expire_on_commit=False
    )
    runner = JobRunner(
        no_autoflush,
        PipelineHandlers(
            get_settings().model_copy(update={"embedding_batch_size": 3})
        ).handlers(),
        worker_id="no-autoflush",
    )

    with installed_fakes() as (_llm, embedders):
        results = drain(runner)

    assert all_completed(results)
    chunk_total = count(Chunk, access.project_id)
    embedder: HashedEmbedder = embedders[0]  # type: ignore[assignment]
    assert embedder.calls == ceil(chunk_total / 3)


def test_identical_upload_fails_cleanly_and_the_queue_keeps_working(
    clean_database,
) -> None:
    access = create_project()
    upload(access, "BrakeController_HLD.md", V1.read_bytes())
    with installed_fakes():
        drain(real_runner())
        # same bytes under another name: rejected by the ingestion job, not by crashing the worker
        duplicate_id = upload(access, "Copy.md", V1.read_bytes())
        results = drain(real_runner())

    assert states(results) == [("DOCUMENT_INGESTION", "FAILED")]
    with get_session_factory()() as session:
        job = session.get(Job, duplicate_id)
        assert job is not None and job.state is JobState.FAILED
        assert "identical source file" in job.details["failure_message"]
    assert count(Document, access.project_id) == 1  # no half-written second document


def test_second_revision_becomes_version_two_and_keeps_version_one(
    clean_database,
) -> None:
    access = create_project()
    upload(access, "BrakeController_HLD.md", V1.read_bytes())
    upload(access, "BrakeController_HLD.md", V2.read_bytes())
    with installed_fakes():
        results = drain(real_runner())

    assert all_completed(results)
    with get_session_factory()() as session:
        versions = list(
            session.scalars(
                select(DocumentVersion).order_by(DocumentVersion.version_number)
            )
        )
        assert [item.version_number for item in versions] == [1, 2]
        assert len({item.document_id for item in versions}) == 1
        for version in versions:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(Chunk)
                    .where(Chunk.document_version_id == version.id)
                )
                >= 3
            )


def test_corrupt_pdf_fails_without_leaving_partial_rows(clean_database) -> None:
    access = create_project()
    upload(
        access, "broken.pdf", b"%PDF-1.7 definitely not a pdf", media="application/pdf"
    )
    with installed_fakes():
        results = drain(real_runner())

    assert states(results) == [("DOCUMENT_INGESTION", "FAILED")]
    assert count(Document, access.project_id) == 0
    assert count(Section, access.project_id) == 0
