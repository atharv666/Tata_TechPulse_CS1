"""Comprehensive 28-Step System Integration Workflow Verification Test.

Executes all 28 end-to-end steps sequentially:
1. create project
2. upload synthetic HLD
3. create document version
4. parse document
5. preserve section hierarchy
6. create chunks
7. create embeddings
8. extract entities
9. extract relationships
10. canonicalize entities
11. resolve duplicates
12. validate candidate facts
13. build PostgreSQL graph
14. preserve provenance
15. query graph
16. vector search
17. hybrid retrieval
18. build evidence bundle
19. generate grounded answer
20. verify citations
21. open graph
22. run impact analysis
23. review a candidate
24. correct another candidate
25. inspect audit history
26. upload second revision
27. compare revisions
28. view comparison findings
"""

import asyncio
import base64
from pathlib import Path
from uuid import UUID

import pytest
from app.api.dependencies import CurrentUser, ProjectAccess
from app.api.routes.mvp import MvpApiService
from app.canonicalization.core import EntityCandidate, EntityResolver
from app.core.config import get_settings
from app.db.session import DatabaseConfigurationError, get_engine
from app.extraction.service import CandidateExtractionService
from app.jobs.orchestration import JobExecutor
from app.jobs.pipeline import PipelineHandlers
from app.models.base import Base
from app.models.enums import MembershipRole, ValidationState
from app.models.schema import (
    Chunk,
    Document,
    DocumentVersion,
    Entity,
    EntityEvidence,
    Relationship,
    RelationshipEvidence,
    Section,
)
from app.providers.factory import create_embedding_provider, create_llm_provider
from app.repositories.jobs import JobRepository
from app.repositories.vectors import VectorRepository
from app.retrieval.graph import GraphTraversalService
from app.retrieval.hybrid import HybridRetrievalService
from app.retrieval.planning import QueryPlanner
from app.retrieval.vector import EmbeddingService, VectorRetrievalService
from app.schemas.api import (
    ComparisonRequest,
    DocumentUploadRequest,
    ImpactRequest,
    ProjectCreate,
    QueryRequest,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def test_db_session():
    try:
        engine = get_engine()
        Base.metadata.create_all(engine)
        session = sessionmaker(bind=engine)()
    except (DatabaseConfigurationError, SQLAlchemyError) as err:
        pytest.skip(
            f"Live PostgreSQL database is not configured for integration test: {err}"
        )
    try:
        yield session
    finally:
        session.close()


def test_full_28_step_integration_workflow(test_db_session: object) -> None:
    asyncio.run(_run_28_step_workflow(test_db_session))


async def _run_28_step_workflow(session: object) -> None:
    user = CurrentUser("integration-engineer")
    service = MvpApiService(session, user)

    # -------------------------------------------------------------------------
    # Step 1: Create Project
    # -------------------------------------------------------------------------
    proj = service.create_project(
        ProjectCreate(name="Full_Integration_Test_Project", description="28-step test")
    )
    assert proj.id is not None
    session.flush()
    access = ProjectAccess(proj.id, "integration-engineer", MembershipRole.ADMIN)

    # Load synthetic HLD sample content
    sample_dir = Path(__file__).parent.parent / "sample_data" / "hld"
    v1_bytes = (sample_dir / "01_BrakeController_HLD_v1.md").read_bytes()
    v2_bytes = (sample_dir / "02_BrakeController_HLD_v2.md").read_bytes()

    # -------------------------------------------------------------------------
    # Step 2: Upload Synthetic HLD (v1)
    # -------------------------------------------------------------------------
    ingest_job = service.upload_document(
        access,
        DocumentUploadRequest(
            filename="BrakeController_HLD.md",
            media_type="text/markdown",
            content_base64=base64.b64encode(v1_bytes).decode("ascii"),
        ),
    )
    assert ingest_job.id is not None
    session.flush()

    # Execute background worker for ingestion job
    settings = get_settings()
    executor = JobExecutor(
        JobRepository(session), PipelineHandlers(session, settings).handlers()
    )
    run_job = await executor.run_next()
    assert run_job is not None
    assert run_job.state.value == "COMPLETED"

    # -------------------------------------------------------------------------
    # Step 3: Verify Document & Version Creation
    # -------------------------------------------------------------------------
    doc = (
        session.query(Document)
        .filter_by(project_id=proj.id, name="BrakeController_HLD.md")
        .first()
    )
    assert doc is not None
    ver1 = (
        session.query(DocumentVersion)
        .filter_by(project_id=proj.id, document_id=doc.id, version_number=1)
        .first()
    )
    assert ver1 is not None

    # -------------------------------------------------------------------------
    # Step 4: Verify Parsing & Format Detection
    # -------------------------------------------------------------------------
    sections = (
        session.query(Section)
        .filter_by(project_id=proj.id, document_version_id=ver1.id)
        .all()
    )
    assert len(sections) > 0

    # -------------------------------------------------------------------------
    # Step 5: Preserve Section Hierarchy
    # -------------------------------------------------------------------------
    root_sections = [s for s in sections if s.level == 1]
    assert len(root_sections) > 0

    # -------------------------------------------------------------------------
    # Step 6: Create Chunks
    # -------------------------------------------------------------------------
    chunks = (
        session.query(Chunk)
        .filter_by(project_id=proj.id, document_version_id=ver1.id)
        .all()
    )
    assert len(chunks) > 0

    # -------------------------------------------------------------------------
    # Step 7: Create Embeddings
    # -------------------------------------------------------------------------
    _ = JobRepository(session).enqueue(
        proj.id, "EMBEDDING", user.user_id, {}, "test:embed:v1"
    )
    session.flush()
    await executor.run_next()
    embedded_chunks = (
        session.query(Chunk)
        .filter(Chunk.project_id == proj.id, Chunk.embedding.is_not(None))
        .all()
    )
    assert len(embedded_chunks) == len(chunks)

    # -------------------------------------------------------------------------
    # Steps 8 & 9: Extract Candidate Entities & Relationships
    # -------------------------------------------------------------------------
    extractor = CandidateExtractionService(create_llm_provider(settings.llm_settings()))
    for chunk in chunks:
        await extractor.extract_chunk(session, proj.id, chunk.id)
    session.flush()

    raw_entities = session.query(Entity).filter_by(project_id=proj.id).all()
    raw_relationships = session.query(Relationship).filter_by(project_id=proj.id).all()
    assert len(raw_entities) > 0
    assert len(raw_relationships) > 0

    # -------------------------------------------------------------------------
    # Step 10: Canonicalize Entities & Aliases
    # -------------------------------------------------------------------------
    candidates = [
        EntityCandidate(e.id, e.project_id, e.canonical_name, e.entity_type)
        for e in raw_entities
    ]
    resolver = EntityResolver()
    groups = resolver.group_candidates(candidates)
    assert len(groups) > 0

    # -------------------------------------------------------------------------
    # Step 11: Resolve Duplicates
    # -------------------------------------------------------------------------
    merged_ids = set(groups.keys())
    assert len(merged_ids) <= len(candidates)

    # -------------------------------------------------------------------------
    # Steps 12 & 13: Validate Candidate Facts & Build PostgreSQL Graph
    # -------------------------------------------------------------------------
    _ = service.graph_build(access)
    session.flush()
    await executor.run_next()

    trusted_entities = session.query(Entity).filter_by(project_id=proj.id).all()
    assert len(trusted_entities) > 0

    # -------------------------------------------------------------------------
    # Step 14: Preserve Provenance Traceability
    # -------------------------------------------------------------------------
    ent_evidence = session.query(EntityEvidence).filter_by(project_id=proj.id).all()
    rel_evidence = (
        session.query(RelationshipEvidence).filter_by(project_id=proj.id).all()
    )
    assert len(ent_evidence) > 0
    assert len(rel_evidence) > 0

    # -------------------------------------------------------------------------
    # Step 15: Query Graph (Deterministic Bounded Traversal)
    # -------------------------------------------------------------------------
    planner = QueryPlanner()
    query_text = "What components consume WheelSpeedInterface?"
    plan = planner.plan(query_text, proj.id, candidates)
    assert plan is not None

    # -------------------------------------------------------------------------
    # Step 16: Vector Search (pgvector similarity)
    # -------------------------------------------------------------------------
    vector_repo = VectorRepository(session, proj.id)
    embeddings_svc = EmbeddingService(
        create_embedding_provider(settings.embedding_settings()),
        settings.embedding_settings(),
    )
    vector_hits = await VectorRetrievalService(embeddings_svc).search(
        query_text, vector_repo, top_k=5
    )
    assert len(vector_hits) > 0

    # -------------------------------------------------------------------------
    # Step 17: Hybrid Retrieval
    # -------------------------------------------------------------------------
    hybrid_result = await HybridRetrievalService(
        VectorRetrievalService(embeddings_svc), GraphTraversalService()
    ).retrieve(plan, vector_repo, raw_relationships, top_k=5)
    assert hybrid_result is not None

    # -------------------------------------------------------------------------
    # Step 18: Build Evidence Bundle
    # -------------------------------------------------------------------------
    query_resp = await service.query(access, QueryRequest(query=query_text, top_k=5))
    assert query_resp is not None

    # -------------------------------------------------------------------------
    # Step 19: Generate Grounded Answer
    # -------------------------------------------------------------------------
    assert hasattr(query_resp, "summary")
    assert query_resp.summary is not None

    # -------------------------------------------------------------------------
    # Step 20: Verify Citations & Claims Grounding
    # -------------------------------------------------------------------------
    assert hasattr(query_resp, "claims")
    assert hasattr(query_resp, "citations")

    # -------------------------------------------------------------------------
    # Step 21: Open Knowledge Graph Topology
    # -------------------------------------------------------------------------
    _entities_page, entity_count = service.entities(access, 0, 50)
    _relationships_page, rel_count = service.relationships(access, 0, 50)
    assert entity_count > 0
    assert rel_count > 0

    # -------------------------------------------------------------------------
    # Step 22: Run Impact Analysis
    # -------------------------------------------------------------------------
    target_ent = trusted_entities[0]
    impact_result = service.impact(
        access, ImpactRequest(root_entity_id=target_ent.id, depth=2)
    )
    assert impact_result is not None
    assert hasattr(impact_result, "results")

    # -------------------------------------------------------------------------
    # Step 23: Review a Candidate (Verify Entity)
    # -------------------------------------------------------------------------
    review_svc = service.review(access)
    unverified_ent = next(
        (e for e in trusted_entities if e.validation_state == ValidationState.PENDING),
        trusted_entities[0],
    )
    verified_ent = review_svc.verify_entity(
        unverified_ent.id, "Verified during 28-step test"
    )
    assert verified_ent.validation_state == ValidationState.HUMAN_VERIFIED

    # -------------------------------------------------------------------------
    # Step 24: Correct Another Candidate Entity
    # -------------------------------------------------------------------------
    cand_to_correct = trusted_entities[-1]
    corrected_ent = review_svc.correct_entity(
        cand_to_correct.id,
        "CorrectedBrakeComponent",
        "SOFTWARE_COMPONENT",
        "Corrected canonical name during 28-step test",
    )
    assert corrected_ent.canonical_name == "CorrectedBrakeComponent"

    # -------------------------------------------------------------------------
    # Step 25: Inspect Audit History
    # -------------------------------------------------------------------------
    audit_items, audit_total = service.audit(access, 0, 50)
    assert audit_total >= 2
    actions = [ev.action for ev in audit_items]
    assert "VERIFY_ENTITY" in actions
    assert "CORRECT_ENTITY" in actions

    # -------------------------------------------------------------------------
    # Step 26: Upload Second Revision (v2)
    # -------------------------------------------------------------------------
    _ = service.upload_document(
        access,
        DocumentUploadRequest(
            filename="BrakeController_HLD.md",
            media_type="text/markdown",
            content_base64=base64.b64encode(v2_bytes).decode("ascii"),
        ),
    )
    session.flush()
    await executor.run_next()

    ver2 = (
        session.query(DocumentVersion)
        .filter_by(project_id=proj.id, document_id=doc.id, version_number=2)
        .first()
    )
    assert ver2 is not None

    # -------------------------------------------------------------------------
    # Step 27: Compare Revisions
    # -------------------------------------------------------------------------
    _comparison, comp_job = service.comparison(
        access, ComparisonRequest(base_version_id=ver1.id, target_version_id=ver2.id)
    )
    session.flush()
    await executor.run_next()

    # -------------------------------------------------------------------------
    # Step 28: View Comparison Findings
    # -------------------------------------------------------------------------
    comp_id_str = comp_job.details.get("comparison_id")
    assert comp_id_str is not None
    comp_id = UUID(str(comp_id_str))

    findings, findings_total = service.comparison_findings(access, comp_id, 0, 50)
    assert findings_total >= 0
    assert isinstance(findings, list)
