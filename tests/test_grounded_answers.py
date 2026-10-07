"""Evidence assembly and grounded-answer validation tests using FakeLLMProvider."""

import asyncio
from uuid import UUID, uuid4

import pytest
from app.models.enums import ExtractionType, ValidationState
from app.providers.fake import FakeLLMProvider
from app.repositories.vectors import VectorSearchHit
from app.retrieval.evidence import (
    EvidenceAssemblyService,
    GraphFactEvidence,
    GroundedAnswerService,
)


def run(coroutine: object) -> object:
    return asyncio.run(coroutine)  # type: ignore[arg-type]


def hit(
    content: str = "BrakeController requires WheelSpeedInterface.",
    version: UUID | None = None,
) -> VectorSearchHit:
    return VectorSearchHit(
        chunk_id=uuid4(),
        document_version_id=version or uuid4(),
        document_id=uuid4(),
        document_name="HLD",
        section_id=uuid4(),
        section_heading="Interfaces",
        content=content,
        page_start=4,
        page_end=4,
        distance=0.1,
    )


def test_successful_grounded_answer_with_multiple_citations_and_inferred_claim() -> (
    None
):
    first, second = hit(), hit("WheelSpeedInterface is provided by SensorComponent.")
    bundle = EvidenceAssemblyService().assemble(
        uuid4(), "What requires WheelSpeedInterface?", [first, second], []
    )
    payload = {
        "status": "DRAFT",
        "summary": "BrakeController requires WheelSpeedInterface.",
        "claims": [
            {
                "text": "BrakeController requires WheelSpeedInterface.",
                "citation_ids": [f"chunk:{first.chunk_id}", f"chunk:{second.chunk_id}"],
                "extraction_type": "INFERRED",
            }
        ],
    }
    answer = run(GroundedAnswerService(FakeLLMProvider(payload)).answer(bundle))

    assert answer.status == "GROUNDED"  # type: ignore[union-attr]
    assert len(answer.citations) == 2  # type: ignore[union-attr]
    assert answer.claims[0].extraction_type is ExtractionType.INFERRED  # type: ignore[union-attr]


def test_insufficient_evidence_and_bounded_additional_retrieval() -> None:
    empty = EvidenceAssemblyService().assemble(uuid4(), "unknown", [], [])
    answer = run(GroundedAnswerService(FakeLLMProvider({})).answer(empty))
    assert answer.insufficient_evidence  # type: ignore[union-attr]


def test_additional_retrieval_is_used_within_bound() -> None:
    recovered = EvidenceAssemblyService().assemble(uuid4(), "known", [hit()], [])
    calls = 0

    async def retrieve() -> object:
        nonlocal calls
        calls += 1
        return recovered

    answer = run(
        GroundedAnswerService(
            FakeLLMProvider({"status": "DRAFT", "summary": "known"})
        ).answer(
            EvidenceAssemblyService().assemble(uuid4(), "unknown", [], []),
            retrieve,
            max_rounds=2,
        )
    )
    assert answer.status == "GROUNDED"  # type: ignore[union-attr]
    assert calls == 1


def test_conflicting_evidence_is_surfaced() -> None:
    source = hit()
    citation_id = f"chunk:{source.chunk_id}"
    facts = [
        GraphFactEvidence(
            fact_id="1",
            source_entity="Interface",
            relationship_type="PROVIDES",
            target_entity="A",
            confidence=0.9,
            extraction_type=ExtractionType.EXPLICIT,
            validation_state=ValidationState.PENDING,
            citation_ids=[citation_id],
        ),
        GraphFactEvidence(
            fact_id="2",
            source_entity="Interface",
            relationship_type="PROVIDES",
            target_entity="B",
            confidence=0.9,
            extraction_type=ExtractionType.EXPLICIT,
            validation_state=ValidationState.PENDING,
            citation_ids=[citation_id],
        ),
    ]
    bundle = EvidenceAssemblyService().assemble(uuid4(), "providers", [source], facts)
    assert bundle.conflicts


def test_invalid_citation_and_unsupported_claim_are_rejected() -> None:
    source = hit()
    bundle = EvidenceAssemblyService().assemble(uuid4(), "question", [source], [])
    invalid = {
        "status": "DRAFT",
        "summary": "x",
        "claims": [
            {
                "text": "invented architecture",
                "citation_ids": ["chunk:missing"],
                "extraction_type": "EXPLICIT",
            }
        ],
    }
    with pytest.raises(ValueError, match="invalid citation"):
        run(GroundedAnswerService(FakeLLMProvider(invalid)).answer(bundle))
    unsupported = {
        "status": "DRAFT",
        "summary": "x",
        "claims": [
            {
                "text": "invented architecture",
                "citation_ids": [f"chunk:{source.chunk_id}"],
                "extraction_type": "EXPLICIT",
            }
        ],
    }
    with pytest.raises(ValueError, match="unsupported"):
        run(GroundedAnswerService(FakeLLMProvider(unsupported)).answer(bundle))


def test_source_version_mismatch_drops_graph_fact() -> None:
    version, other_version = uuid4(), uuid4()
    first, second = hit(version=version), hit(version=other_version)
    fact = GraphFactEvidence(
        fact_id="1",
        source_entity="A",
        relationship_type="USES",
        target_entity="B",
        confidence=0.9,
        extraction_type=ExtractionType.EXPLICIT,
        validation_state=ValidationState.PENDING,
        citation_ids=[f"chunk:{second.chunk_id}"],
    )
    bundle = EvidenceAssemblyService().assemble(
        uuid4(), "q", [first, second], [fact], document_version_id=version
    )
    assert not bundle.graph_facts
