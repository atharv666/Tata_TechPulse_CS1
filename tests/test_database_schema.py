"""Fast database foundation tests that do not require a running PostgreSQL server."""

from app.core.config import get_settings
from app.models import Base
from app.models.enums import ExtractionType, TrustState, ValidationState

EXPECTED_TABLES = {
    "projects",
    "project_members",
    "documents",
    "document_versions",
    "sections",
    "chunks",
    "entities",
    "entity_aliases",
    "relationships",
    "entity_evidence",
    "relationship_evidence",
    "validation_events",
    "audit_events",
    "jobs",
    "comparisons",
    "comparison_findings",
}


def test_complete_mvp_table_inventory_is_mapped() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_foreign_keys_capture_document_and_provenance_paths() -> None:
    chunk_targets = {
        key.target_fullname for key in Base.metadata.tables["chunks"].foreign_keys
    }
    evidence_targets = {
        key.target_fullname
        for key in Base.metadata.tables["relationship_evidence"].foreign_keys
    }

    assert {"projects.id", "document_versions.id", "sections.id"}.issubset(
        chunk_targets
    )
    assert {"projects.id", "relationships.id", "chunks.id"}.issubset(evidence_targets)


def test_relationship_is_directed_and_has_distinct_endpoints() -> None:
    relationship_table = Base.metadata.tables["relationships"]
    assert {"source_entity_id", "target_entity_id"}.issubset(
        relationship_table.columns.keys()
    )
    assert any(
        "source_entity_id <> target_entity_id" in str(item.sqltext)
        for item in relationship_table.constraints
        if hasattr(item, "sqltext")
    )


def test_candidate_trusted_and_human_validation_vocabularies_are_preserved() -> None:
    assert {TrustState.CANDIDATE, TrustState.TRUSTED} == set(TrustState)
    assert {ExtractionType.EXPLICIT, ExtractionType.INFERRED} == set(ExtractionType)
    assert {
        ValidationState.PENDING,
        ValidationState.HUMAN_VERIFIED,
        ValidationState.HUMAN_CORRECTED,
        ValidationState.REJECTED,
    } == set(ValidationState)


def test_vector_column_uses_configured_dimension() -> None:
    vector_type = Base.metadata.tables["chunks"].columns["embedding"].type
    assert vector_type.dim == get_settings().embedding_dimensions


def test_chunks_track_successful_candidate_extraction() -> None:
    assert "extracted_at" in Base.metadata.tables["chunks"].columns


def test_validation_events_require_exactly_one_fact_target() -> None:
    constraints = Base.metadata.tables["validation_events"].constraints
    assert any(
        "entity_id IS NOT NULL" in str(item.sqltext)
        for item in constraints
        if hasattr(item, "sqltext")
    )
