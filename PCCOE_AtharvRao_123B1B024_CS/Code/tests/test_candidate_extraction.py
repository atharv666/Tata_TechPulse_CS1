"""Candidate extraction against PostgreSQL with deterministic provider output.

The model only proposes; this stage validates each item against the chunk text and stages
relationships by endpoint *name* for the resolution stage to bind.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from app.extraction.prompts import EXTRACTION_PROMPT_VERSION, build_extraction_prompt
from app.extraction.schemas import ChunkExtraction
from app.extraction.service import (
    CandidateExtractionService,
    locate_excerpt,
    normalize_name,
)
from app.models.enums import (
    ExtractionType,
    SourceClassification,
    TrustState,
    ValidationState,
)
from app.models.schema import (
    Entity,
    EntityAlias,
    EntityEvidence,
    Relationship,
    RelationshipCandidate,
)
from app.providers.fake import FakeLLMProvider
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.support.graph import GraphBuilder

pytestmark = pytest.mark.usefixtures("clean_database")

TEXT = "BrakeController REQUIRES WheelSpeedInterface."


def payload(**overrides: Any) -> dict[str, Any]:
    evidence = {"excerpt": TEXT, "source_type": "DIRECT_TEXT"}
    data: dict[str, Any] = {
        "entities": [
            {
                "name": "BrakeController",
                "entity_type": "SOFTWARE_COMPONENT",
                "confidence": 0.95,
                "extraction_type": "EXPLICIT",
                "evidence": evidence,
                "aliases": ["BrakeCtrl"],
            },
            {
                "name": "WheelSpeedInterface",
                "entity_type": "INTERFACE",
                "confidence": 0.93,
                "extraction_type": "EXPLICIT",
                "evidence": evidence,
            },
        ],
        "relationships": [
            {
                "source_name": "BrakeController",
                "target_name": "WheelSpeedInterface",
                "relationship_type": "REQUIRES",
                "confidence": 0.91,
                "extraction_type": "EXPLICIT",
                "evidence": evidence,
            }
        ],
    }
    data.update(overrides)
    return data


def extract(
    session: Session, graph: GraphBuilder, chunk_text: str, data: dict[str, Any]
):  # type: ignore[no-untyped-def]
    chunk = graph.chunk(chunk_text)
    result = asyncio.run(
        CandidateExtractionService(FakeLLMProvider(data)).extract_chunk(
            session, graph.project_id, chunk.id
        )
    )
    session.flush()
    return chunk, result


def test_extraction_persists_pending_entities_and_stages_relationships_by_name(
    db_session: Session,
) -> None:
    graph = GraphBuilder(db_session)
    chunk, result = extract(db_session, graph, TEXT, payload())

    entities = list(db_session.scalars(select(Entity).order_by(Entity.canonical_name)))
    assert (result.entity_count, result.relationship_count, result.alias_count) == (
        2,
        1,
        1,
    )
    assert all(
        e.trust_state is TrustState.CANDIDATE
        and e.validation_state is ValidationState.PENDING
        and e.extraction_type is ExtractionType.EXPLICIT
        and e.raw_confidence == e.confidence
        for e in entities
    )
    assert (
        entities[0].extraction_metadata["prompt_version"] == EXTRACTION_PROMPT_VERSION
    )
    # no trusted relationship is created here: only a candidate keyed by the endpoint names
    assert db_session.scalars(select(Relationship)).all() == []
    candidate = db_session.scalars(select(RelationshipCandidate)).one()
    assert (candidate.source_name, candidate.target_name) == (
        "BrakeController",
        "WheelSpeedInterface",
    )
    assert candidate.chunk_id == chunk.id and candidate.status == "UNBOUND"
    assert candidate.excerpt == TEXT
    assert chunk.extracted_at is not None
    evidence = db_session.scalars(select(EntityEvidence)).all()
    assert len(evidence) == 2 and all(e.chunk_id == chunk.id for e in evidence)
    alias = db_session.scalars(select(EntityAlias)).one()
    assert (alias.alias, alias.source) == ("BrakeCtrl", "EXPLICIT")


def test_a_relationship_may_name_an_entity_defined_somewhere_else(
    db_session: Session,
) -> None:
    graph = GraphBuilder(db_session)
    data = payload()
    data["entities"] = data["entities"][
        :1
    ]  # the interface is not defined in this chunk

    _, result = extract(db_session, graph, TEXT, data)

    assert (
        result.relationship_count == 1
    )  # kept: the target may be defined in another section
    assert db_session.scalars(select(RelationshipCandidate)).one().target_name == (
        "WheelSpeedInterface"
    )


def test_one_bad_item_is_rejected_without_losing_the_rest_of_the_chunk(
    db_session: Session,
) -> None:
    graph = GraphBuilder(db_session)
    data = payload()
    data["entities"][0]["evidence"] = {
        "excerpt": "invented text",
        "source_type": "DIRECT_TEXT",
    }

    _, result = extract(db_session, graph, TEXT, data)

    assert result.entity_count == 1 and result.relationship_count == 1
    assert any("evidence excerpt not in chunk" in item for item in result.rejected)
    assert [e.canonical_name for e in db_session.scalars(select(Entity))] == [
        "WheelSpeedInterface"
    ]


def test_evidence_quoted_with_different_spacing_or_markup_is_still_located(
    db_session: Session,
) -> None:
    graph = GraphBuilder(db_session)
    text = "The `BrakeController`  REQUIRES\n`WheelSpeedInterface`."
    data = payload()
    for item in (*data["entities"], *data["relationships"]):
        item["evidence"]["excerpt"] = "BrakeController requires WheelSpeedInterface"

    _, result = extract(db_session, graph, text, data)

    assert (
        result.entity_count == 2
        and result.relationship_count == 1
        and not result.rejected
    )
    stored = db_session.scalars(select(EntityEvidence)).first()
    assert (
        stored is not None and stored.excerpt in text
    )  # the stored excerpt is the real text


def test_locate_excerpt_forgives_formatting_but_not_content() -> None:
    content = "The `A`  uses\nB."
    assert locate_excerpt(content, "A uses B") == (5, 15)
    assert locate_excerpt(content, "A uses C") is None
    assert locate_excerpt(content, "") is None


def test_a_self_relationship_is_rejected_by_the_schema() -> None:
    bad = payload()
    bad["relationships"][0]["target_name"] = "brakecontroller"
    with pytest.raises(ValidationError):
        ChunkExtraction.model_validate(bad)


def test_unsupported_taxonomy_is_rejected_by_structured_schema() -> None:
    invalid = payload()
    invalid["entities"][0]["entity_type"] = "UNSUPPORTED"
    with pytest.raises(ValidationError):
        ChunkExtraction.model_validate(invalid)
    invalid = payload()
    invalid["relationships"][0]["relationship_type"] = "CONTRADICTS"
    with pytest.raises(ValidationError):
        ChunkExtraction.model_validate(invalid)


def test_repeated_extraction_keeps_the_best_claim_regardless_of_order(
    db_session: Session,
) -> None:
    graph = GraphBuilder(db_session)
    low = payload()
    low["entities"][0].update(confidence=0.5, extraction_type="INFERRED")
    high = payload()
    high["entities"][0].update(confidence=0.9, extraction_type="EXPLICIT")

    extract(db_session, graph, TEXT, high)
    extract(db_session, graph, TEXT, low)

    entity = db_session.scalars(
        select(Entity).where(Entity.canonical_name == "BrakeController")
    ).one()
    assert float(entity.raw_confidence or 0) == pytest.approx(0.9)  # max(0.9, 0.5)
    assert entity.extraction_type is ExtractionType.EXPLICIT
    assert (
        len(db_session.scalars(select(EntityEvidence)).all()) == 4
    )  # 2 entities x 2 chunks


def test_text_recovered_by_ocr_is_always_labelled_as_such(db_session: Session) -> None:
    graph = GraphBuilder(db_session)
    chunk = graph.chunk(TEXT)
    chunk.chunk_kind = "OCR_TEXT"
    db_session.flush()

    asyncio.run(
        CandidateExtractionService(FakeLLMProvider(payload())).extract_chunk(
            db_session, graph.project_id, chunk.id
        )
    )

    classes = {
        e.source_classification for e in db_session.scalars(select(EntityEvidence))
    }
    assert classes == {SourceClassification.OCR_TEXT}
    assert db_session.scalars(
        select(RelationshipCandidate)
    ).one().source_classification == ("OCR_TEXT")


def test_an_alias_owned_by_another_entity_is_recorded_not_overwritten(
    db_session: Session,
) -> None:
    graph = GraphBuilder(db_session)
    graph.entity("OtherController", aliases=("BrakeCtrl",))

    extract(db_session, graph, TEXT, payload())

    owners = db_session.scalars(
        select(EntityAlias).where(EntityAlias.alias == "BrakeCtrl")
    ).all()
    assert len(owners) == 1  # still the original owner
    brake = db_session.scalars(
        select(Entity).where(Entity.canonical_name == "BrakeController")
    ).one()
    assert brake.extraction_metadata["alias_conflicts"] == ["BrakeCtrl"]


def test_a_chunk_from_another_project_is_not_extractable(db_session: Session) -> None:
    graph, other = GraphBuilder(db_session, "a"), GraphBuilder(db_session, "b")
    chunk = graph.chunk(TEXT)
    with pytest.raises(ValueError, match="requested project"):
        asyncio.run(
            CandidateExtractionService(FakeLLMProvider(payload())).extract_chunk(
                db_session, other.project_id, chunk.id
            )
        )


def test_prompt_is_versioned_constrained_and_carries_the_document_location() -> None:
    prompt = build_extraction_prompt("BrakeController", 3, 3, "HLD > 2 Dependencies")

    assert EXTRACTION_PROMPT_VERSION in prompt
    assert "Allowed entity types" in prompt and "Allowed relationship types" in prompt
    assert "Document location: HLD > 2 Dependencies" in prompt
    assert "aliases" in prompt and "BrakeController" in prompt


def test_normalization_is_exact_lexical_only() -> None:
    assert normalize_name("Brake Controller") == "brakecontroller"
