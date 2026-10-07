"""Candidate extraction tests with deterministic FakeLLMProvider output."""

import asyncio
from uuid import uuid4

import pytest
from app.extraction.prompts import EXTRACTION_PROMPT_VERSION, build_extraction_prompt
from app.extraction.schemas import ChunkExtraction
from app.extraction.service import CandidateExtractionService, normalize_name
from app.models.enums import ExtractionType, TrustState, ValidationState
from app.models.schema import Chunk, Entity, Relationship
from app.providers.fake import FakeLLMProvider
from pydantic import ValidationError


def run(coroutine: object) -> object:
    return asyncio.run(coroutine)  # type: ignore[arg-type]


class MemorySession:
    def __init__(self, chunk: Chunk) -> None:
        self.chunk = chunk
        self.added: list[object] = []
        self._first_scalar = True

    def scalar(self, _: object) -> object | None:
        if self._first_scalar:
            self._first_scalar = False
            return self.chunk
        return None

    def add(self, item: object) -> None:
        self.added.append(item)

    def flush(self) -> None:
        for item in self.added:
            if isinstance(item, (Entity, Relationship)) and item.id is None:
                item.id = uuid4()


def make_chunk() -> Chunk:
    return Chunk(
        project_id=uuid4(),
        document_version_id=uuid4(),
        section_id=uuid4(),
        ordinal=1,
        content="BrakeController REQUIRES WheelSpeedInterface.",
        token_count=3,
        page_start=2,
        page_end=2,
    )


def payload() -> dict[str, object]:
    evidence = {
        "excerpt": "BrakeController REQUIRES WheelSpeedInterface.",
        "source_type": "DIRECT_TEXT",
    }
    return {
        "entities": [
            {
                "name": "BrakeController",
                "entity_type": "SOFTWARE_COMPONENT",
                "confidence": 0.95,
                "extraction_type": "EXPLICIT",
                "evidence": evidence,
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


def test_structured_candidate_extraction_persists_only_pending_facts_with_evidence() -> (
    None
):
    chunk = make_chunk()
    session = MemorySession(chunk)
    result = run(
        CandidateExtractionService(FakeLLMProvider(payload())).extract_chunk(
            session, chunk.project_id, chunk.id
        )
    )

    entities = [item for item in session.added if isinstance(item, Entity)]
    relationships = [item for item in session.added if isinstance(item, Relationship)]
    assert result.entity_count == 2  # type: ignore[union-attr]
    assert result.relationship_count == 1  # type: ignore[union-attr]
    assert all(
        entity.trust_state is TrustState.CANDIDATE
        and entity.validation_state is ValidationState.PENDING
        for entity in entities
    )
    assert all(entity.extraction_type is ExtractionType.EXPLICIT for entity in entities)
    assert relationships[0].source_entity_id == entities[0].id
    assert relationships[0].target_entity_id == entities[1].id
    assert relationships[0].attributes["prompt_version"] == EXTRACTION_PROMPT_VERSION
    assert len(session.added) == 6


def test_unsupported_taxonomy_is_rejected_by_structured_schema() -> None:
    invalid = payload()
    entities = invalid["entities"]
    assert isinstance(entities, list)
    entities[0]["entity_type"] = "UNSUPPORTED"  # type: ignore[index]

    with pytest.raises(ValidationError):
        ChunkExtraction.model_validate(invalid)


def test_evidence_must_be_a_literal_chunk_excerpt() -> None:
    invalid = payload()
    entities = invalid["entities"]
    assert isinstance(entities, list)
    entities[0]["evidence"] = {"excerpt": "invented text", "source_type": "DIRECT_TEXT"}  # type: ignore[index]
    chunk = make_chunk()

    with pytest.raises(ValueError, match="not present"):
        run(
            CandidateExtractionService(FakeLLMProvider(invalid)).extract_chunk(
                MemorySession(chunk), chunk.project_id, chunk.id
            )
        )


def test_prompt_is_versioned_and_constrains_chunk_context() -> None:
    prompt = build_extraction_prompt("BrakeController", 3, 3)

    assert EXTRACTION_PROMPT_VERSION in prompt
    assert "Allowed entity types" in prompt
    assert "Allowed relationship types" in prompt
    assert "BrakeController" in prompt


def test_normalization_is_exact_lexical_only() -> None:
    assert normalize_name("Brake Controller") == "brakecontroller"
