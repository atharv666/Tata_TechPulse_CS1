"""Performance benchmarks for core deterministic pipeline paths."""

from decimal import Decimal
from time import perf_counter
from uuid import uuid4

from app.canonicalization.core import EntityCandidate, EntityResolver, UnionFind
from app.ingestion.chunking import chunk_section
from app.ingestion.contracts import NormalizedSection, ParsedBlock, SourcePosition
from app.models.enums import ExtractionType, TrustState, ValidationState
from app.models.schema import Entity, Relationship
from app.retrieval.evidence import (
    Citation,
    EvidenceBundle,
    EvidenceSufficiencyService,
    GraphFactEvidence,
)
from app.retrieval.impact import ImpactAnalysisService, ImpactSourceEvidence


def test_document_parsing_and_chunking_performance() -> None:
    # Benchmark section-aware chunking over 20 section structures
    sections = [
        NormalizedSection(
            heading=f"Section {i}: AUTOSAR Subsystem Spec",
            level=2,
            position=SourcePosition(page=i),
            content=[
                ParsedBlock(
                    text=f"Detailed specifications for component {i}. " * 50,
                    position=SourcePosition(page=i),
                )
            ],
            children=[],
        )
        for i in range(1, 21)
    ]

    start = perf_counter()
    all_chunks = []
    for section in sections:
        all_chunks.extend(chunk_section(section, max_tokens=150, overlap_tokens=20))
    duration_ms = (perf_counter() - start) * 1000

    assert len(all_chunks) >= 20
    assert duration_ms < 50.0  # Must finish within 50ms threshold


def test_canonicalization_resolution_performance() -> None:
    # Benchmark entity resolution and Union-Find merging for candidate entities
    resolver = EntityResolver(merge_threshold=0.96)
    uf = UnionFind()
    project_id = uuid4()

    candidates = [
        EntityCandidate(
            id=uuid4(),
            project_id=project_id,
            canonical_name=f"BrakeController_Sub_{i % 5}",
            entity_type="SOFTWARE_COMPONENT",
        )
        for i in range(20)
    ]

    start = perf_counter()
    for candidate in candidates:
        uf.find(candidate.id)
        res = resolver.resolve(
            project_id=project_id,
            name=candidate.canonical_name,
            entity_type=candidate.entity_type,
            candidates=candidates,
        )
        if res.entity_id:
            uf.union(candidate.id, res.entity_id)

    groups = uf.groups()
    duration_ms = (perf_counter() - start) * 1000

    assert len(groups) == 20
    assert duration_ms < 100.0  # Must finish within threshold


def test_graph_traversal_and_impact_performance() -> None:
    # Benchmark multi-hop graph dependency path traversal
    project_id = uuid4()
    nodes = [
        Entity(
            id=uuid4(),
            project_id=project_id,
            canonical_name=f"Node_{i}",
            normalized_name=f"node_{i}",
            entity_type="INTERFACE" if i % 2 == 0 else "COMPONENT",
            trust_state=TrustState.TRUSTED,
            extraction_type=ExtractionType.EXPLICIT,
            validation_state=ValidationState.HUMAN_VERIFIED,
            confidence=Decimal("0.95"),
            extraction_metadata={},
        )
        for i in range(30)
    ]

    # Create a linear dependency chain: Node_0 -> Node_1 -> Node_2 -> ... -> Node_29
    edges = [
        Relationship(
            id=uuid4(),
            project_id=project_id,
            source_entity_id=nodes[i + 1].id,
            target_entity_id=nodes[i].id,
            relationship_type="REQUIRES",
            trust_state=TrustState.TRUSTED,
            extraction_type=ExtractionType.EXPLICIT,
            validation_state=ValidationState.HUMAN_VERIFIED,
            confidence=Decimal("0.95"),
            attributes={},
        )
        for i in range(29)
    ]

    evidence_map = {
        node.id: ImpactSourceEvidence(
            fact=GraphFactEvidence(
                fact_id=str(node.id),
                source_entity=node.canonical_name,
                relationship_type="EXPLICIT",
                target_entity=node.canonical_name,
                confidence=0.95,
                extraction_type=ExtractionType.EXPLICIT,
                validation_state=ValidationState.HUMAN_VERIFIED,
                citation_ids=[f"cit_{node.id}"],
            ),
            citations=[
                Citation(
                    citation_id=f"cit_{node.id}",
                    chunk_id=uuid4(),
                    document_id=uuid4(),
                    document_version_id=uuid4(),
                    document_name="HLD.pdf",
                    section_heading="Spec",
                    page_start=1,
                    page_end=1,
                    excerpt="Valid evidence excerpt",
                )
            ],
        )
        for node in nodes
    }

    service = ImpactAnalysisService()

    start = perf_counter()
    res = service.analyze(
        project_id=project_id,
        root_entity_id=nodes[0].id,
        entities=nodes,
        relationships=edges,
        evidence=evidence_map,
        depth=3,
        node_limit=100,
        edge_limit=200,
    )
    duration_ms = (perf_counter() - start) * 1000

    assert len(res.results) > 0
    assert duration_ms < 50.0  # Must finish within 50ms threshold


def test_evidence_assembly_and_citation_dedup_performance() -> None:
    # Benchmark evidence sufficiency evaluation and citation matching
    citations = [
        Citation(
            citation_id=f"cit_{i}",
            chunk_id=uuid4(),
            document_id=uuid4(),
            document_version_id=uuid4(),
            document_name=f"Spec_{i % 3}.pdf",
            section_heading=f"Section {i}",
            page_start=i,
            page_end=i,
            excerpt=f"Excerpt text for citation {i}",
        )
        for i in range(50)
    ]

    bundle = EvidenceBundle(
        project_id=uuid4(),
        query="What is the architecture?",
        citations=citations,
        graph_facts=[],
    )

    service = EvidenceSufficiencyService()

    start = perf_counter()
    is_sufficient = service.sufficient(bundle)
    duration_ms = (perf_counter() - start) * 1000

    assert is_sufficient is True
    assert duration_ms < 5.0  # Must finish within 5ms threshold
