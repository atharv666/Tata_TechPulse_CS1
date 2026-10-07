"""Thin application service facade used by HTTP routes; domain rules remain in domain services."""

from __future__ import annotations

import base64
import hashlib
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentUser, ProjectAccess
from app.canonicalization.core import EntityCandidate
from app.core.config import get_settings
from app.core.errors import ApplicationError
from app.ingestion.contracts import IngestionError
from app.ingestion.validation import validate_upload
from app.jobs.source_store import SourceStore
from app.models.enums import MembershipRole
from app.models.schema import (
    AuditEvent,
    Comparison,
    ComparisonFinding,
    Document,
    DocumentVersion,
    Entity,
    Job,
    Project,
    ProjectMember,
    Relationship,
)
from app.providers.factory import create_embedding_provider, create_llm_provider
from app.repositories.comparisons import ComparisonRepository
from app.repositories.jobs import JobRepository
from app.repositories.projects import ProjectRepository
from app.repositories.review import ReviewRepository
from app.repositories.vectors import VectorRepository
from app.retrieval.evidence import (
    Citation,
    EvidenceAssemblyService,
    GraphFactEvidence,
    GroundedAnswerService,
)
from app.retrieval.graph import GraphTraversalService
from app.retrieval.hybrid import HybridRetrievalService
from app.retrieval.impact import ImpactAnalysisService, ImpactSourceEvidence
from app.retrieval.planning import QueryPlanner
from app.retrieval.revision import RevisionEvidence, RevisionSnapshot
from app.retrieval.vector import EmbeddingService, VectorRetrievalService
from app.schemas.api import (
    ComparisonRequest,
    DocumentUploadRequest,
    ImpactRequest,
    MemberCreate,
    ProjectCreate,
    QueryRequest,
)
from app.services.review import ReviewActor, ReviewService


class MvpApiService:
    def __init__(self, session: Session, user: CurrentUser) -> None:
        self._session = session
        self._user = user

    def create_project(self, request: ProjectCreate) -> Project:
        project = Project(name=request.name, description=request.description)
        repository = ProjectRepository(self._session)
        repository.add(project)
        self._session.flush()
        repository.add_member(
            ProjectMember(
                project_id=project.id, user_id=self._user.user_id, role=MembershipRole.ADMIN
            )
        )
        return project

    def projects(self, offset: int, limit: int) -> tuple[list[Project], int]:
        statement = (
            select(Project)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(ProjectMember.user_id == self._user.user_id)
            .order_by(Project.created_at, Project.id)
        )
        return list(self._session.scalars(statement.offset(offset).limit(limit))), self._count(
            statement
        )

    def add_member(self, access: ProjectAccess, request: MemberCreate) -> ProjectMember:
        self._require_admin(access)
        member = ProjectMember(
            project_id=access.project_id, user_id=request.user_id, role=request.role
        )
        ProjectRepository(self._session).add_member(member)
        return member

    def upload_document(self, access: ProjectAccess, request: DocumentUploadRequest) -> Job:
        try:
            content = base64.b64decode(request.content_base64, validate=True)
        except ValueError as error:
            raise ApplicationError(
                "INVALID_UPLOAD", "content_base64 is not valid base64."
            ) from error
        return self.upload_document_content(
            access, request.filename, request.media_type, content, request.storage_uri
        )

    def upload_document_content(
        self,
        access: ProjectAccess,
        filename: str,
        media_type: str | None,
        content: bytes,
        storage_uri: str = "managed://api-upload",
    ) -> Job:
        """Persist untrusted upload bytes privately and enqueue deterministic ingestion."""
        self._require_engineer(access)
        try:
            validate_upload(filename, media_type, content, get_settings().max_upload_bytes)
        except IngestionError as error:
            raise ApplicationError("INVALID_UPLOAD", str(error)) from error
        job = JobRepository(self._session).enqueue(
            access.project_id,
            "DOCUMENT_INGESTION",
            access.user_id,
            {
                "filename": filename,
                "media_type": media_type,
                "storage_uri": storage_uri,
            },
            f"ingestion:{access.project_id}:{hashlib.sha256(content).hexdigest()}",
        )
        self._session.flush()
        source_key = SourceStore(get_settings().document_source_dir).write(job.id, content)
        details = dict(job.details)
        details["payload"] = {
            **details["payload"],
            "source_key": str(source_key),
            "storage_uri": f"managed://source/{source_key}",
        }
        job.details = details
        return job

    def documents(
        self, access: ProjectAccess, offset: int, limit: int
    ) -> tuple[list[Document], int]:
        statement = (
            select(Document)
            .where(Document.project_id == access.project_id)
            .order_by(Document.created_at)
        )
        return list(self._session.scalars(statement.offset(offset).limit(limit))), self._count(
            statement
        )

    def document_versions(
        self, access: ProjectAccess, document_id: UUID, offset: int, limit: int
    ) -> tuple[list[DocumentVersion], int]:
        statement = (
            select(DocumentVersion)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(DocumentVersion.project_id == access.project_id, Document.id == document_id)
            .order_by(DocumentVersion.version_number)
        )
        return list(self._session.scalars(statement.offset(offset).limit(limit))), self._count(
            statement
        )

    def jobs(self, access: ProjectAccess, offset: int, limit: int) -> tuple[list[Job], int]:
        statement = (
            select(Job).where(Job.project_id == access.project_id).order_by(Job.created_at.desc())
        )
        return list(self._session.scalars(statement.offset(offset).limit(limit))), self._count(
            statement
        )

    def entities(self, access: ProjectAccess, offset: int, limit: int) -> tuple[list[Entity], int]:
        statement = (
            select(Entity)
            .where(Entity.project_id == access.project_id)
            .order_by(Entity.canonical_name)
        )
        return list(self._session.scalars(statement.offset(offset).limit(limit))), self._count(
            statement
        )

    def relationships(
        self, access: ProjectAccess, offset: int, limit: int
    ) -> tuple[list[Relationship], int]:
        statement = select(Relationship).where(Relationship.project_id == access.project_id)
        return list(self._session.scalars(statement.offset(offset).limit(limit))), self._count(
            statement
        )

    def graph_build(self, access: ProjectAccess) -> Job:
        self._require_engineer(access)
        return JobRepository(self._session).enqueue(
            access.project_id, "GRAPH_BUILD", access.user_id, {}, f"graph-build:{access.project_id}"
        )

    def reembed(self, access: ProjectAccess) -> Job:
        """Queue an explicit, project-scoped re-index after an embedding model change."""
        self._require_engineer(access)
        return JobRepository(self._session).enqueue(
            access.project_id,
            "REEMBED",
            access.user_id,
            {},
            f"reembed:{access.project_id}",
        )

    def review(self, access: ProjectAccess) -> ReviewService:
        return ReviewService(
            ReviewRepository(self._session, access.project_id),
            ReviewActor(access.user_id, access.project_id, access.role),
        )

    async def query(self, access: ProjectAccess, request: QueryRequest) -> object:
        entities = list(
            self._session.scalars(select(Entity).where(Entity.project_id == access.project_id))
        )
        candidates = [
            EntityCandidate(entity.id, entity.project_id, entity.canonical_name, entity.entity_type)
            for entity in entities
        ]
        plan = QueryPlanner().plan(
            request.query, access.project_id, candidates, request.document_version_id
        )
        relationships = list(
            self._session.scalars(
                select(Relationship).where(Relationship.project_id == access.project_id)
            )
        )
        settings = get_settings()
        embeddings = EmbeddingService(
            create_embedding_provider(settings.embedding_settings()), settings.embedding_settings()
        )
        hybrid = await HybridRetrievalService(
            VectorRetrievalService(embeddings), GraphTraversalService()
        ).retrieve(
            plan, VectorRepository(self._session, access.project_id), relationships, request.top_k
        )
        names = {entity.id: entity.canonical_name for entity in entities}
        review_repository = ReviewRepository(self._session, access.project_id)
        graph_facts: list[GraphFactEvidence] = []
        citations: list[Citation] = []
        if hybrid.graph is not None:
            for relationship in hybrid.graph.relationships:
                fact_citations = self._citations(
                    review_repository.relationship_provenance(relationship.id)
                )
                citations.extend(fact_citations)
                graph_facts.append(
                    GraphFactEvidence(
                        fact_id=str(relationship.id),
                        source_entity=names.get(
                            relationship.source_entity_id, str(relationship.source_entity_id)
                        ),
                        relationship_type=relationship.relationship_type,
                        target_entity=names.get(
                            relationship.target_entity_id, str(relationship.target_entity_id)
                        ),
                        confidence=float(relationship.confidence),
                        extraction_type=relationship.extraction_type,
                        validation_state=relationship.validation_state,
                        citation_ids=[citation.citation_id for citation in fact_citations],
                    )
                )
        bundle = EvidenceAssemblyService().assemble(
            access.project_id,
            request.query,
            list(hybrid.vector_hits),
            graph_facts,
            request.document_version_id,
            citations,
        )
        return await GroundedAnswerService(create_llm_provider(settings.llm_settings())).answer(
            bundle
        )

    def impact(self, access: ProjectAccess, request: ImpactRequest) -> object:
        entities = list(
            self._session.scalars(select(Entity).where(Entity.project_id == access.project_id))
        )
        relationships = list(
            self._session.scalars(
                select(Relationship).where(Relationship.project_id == access.project_id)
            )
        )
        names = {entity.id: entity.canonical_name for entity in entities}
        review_repository = ReviewRepository(self._session, access.project_id)
        evidence: dict[UUID, ImpactSourceEvidence] = {}
        for relationship in relationships:
            citations = self._citations(review_repository.relationship_provenance(relationship.id))
            if citations:
                evidence[relationship.id] = ImpactSourceEvidence(
                    fact=GraphFactEvidence(
                        fact_id=str(relationship.id),
                        source_entity=names.get(
                            relationship.source_entity_id, str(relationship.source_entity_id)
                        ),
                        relationship_type=relationship.relationship_type,
                        target_entity=names.get(
                            relationship.target_entity_id, str(relationship.target_entity_id)
                        ),
                        confidence=float(relationship.confidence),
                        extraction_type=relationship.extraction_type,
                        validation_state=relationship.validation_state,
                        citation_ids=[citation.citation_id for citation in citations],
                    ),
                    citations=citations,
                )
        return ImpactAnalysisService().analyze(
            access.project_id,
            request.root_entity_id,
            entities,
            relationships,
            evidence,
            request.document_version_id,
            request.depth,
            request.node_limit,
            request.edge_limit,
        )

    def comparison(
        self, access: ProjectAccess, request: ComparisonRequest
    ) -> tuple[Comparison, Job]:
        self._require_engineer(access)
        repository = ComparisonRepository(self._session, access.project_id)
        repository.require_version(request.base_version_id)
        repository.require_version(request.target_version_id)
        job = JobRepository(self._session).enqueue(
            access.project_id,
            "REVISION_COMPARISON",
            access.user_id,
            {
                "base_version_id": str(request.base_version_id),
                "target_version_id": str(request.target_version_id),
            },
            f"comparison:{request.base_version_id}:{request.target_version_id}",
        )
        return Comparison(), job

    def comparison_findings(
        self, access: ProjectAccess, comparison_id: UUID, offset: int, limit: int
    ) -> tuple[list[ComparisonFinding], int]:
        statement = (
            select(ComparisonFinding)
            .where(
                ComparisonFinding.project_id == access.project_id,
                ComparisonFinding.comparison_id == comparison_id,
            )
            .order_by(ComparisonFinding.created_at)
        )
        return list(self._session.scalars(statement.offset(offset).limit(limit))), self._count(
            statement
        )

    def cancel_job(self, access: ProjectAccess, job_id: UUID) -> Job:
        job = JobRepository(self._session).request_cancellation(access.project_id, job_id)
        if job is None:
            raise ApplicationError("JOB_NOT_FOUND", "Job was not found in this project.", 404)
        return job

    def audit(self, access: ProjectAccess, offset: int, limit: int) -> tuple[list[AuditEvent], int]:
        statement = (
            select(AuditEvent)
            .where(AuditEvent.project_id == access.project_id)
            .order_by(AuditEvent.created_at.desc())
        )
        return list(self._session.scalars(statement.offset(offset).limit(limit))), self._count(
            statement
        )

    def _snapshot(self, project_id: UUID, version_id: UUID) -> RevisionSnapshot:
        entities = list(
            self._session.scalars(select(Entity).where(Entity.project_id == project_id))
        )
        relationships = list(
            self._session.scalars(select(Relationship).where(Relationship.project_id == project_id))
        )
        review_repository = ReviewRepository(self._session, project_id)
        entity_evidence = {
            entity.id: RevisionEvidence(
                citations=[
                    citation
                    for citation in self._citations(review_repository.entity_provenance(entity.id))
                    if citation.document_version_id == version_id
                ]
            )
            for entity in entities
        }
        relationship_evidence = {
            relationship.id: RevisionEvidence(
                citations=[
                    citation
                    for citation in self._citations(
                        review_repository.relationship_provenance(relationship.id)
                    )
                    if citation.document_version_id == version_id
                ]
            )
            for relationship in relationships
        }
        return RevisionSnapshot(
            version_id, entities, relationships, entity_evidence, relationship_evidence
        )

    @staticmethod
    def _citations(rows: list[tuple[Any, Any, Any, Any, Any]]) -> list[Citation]:
        return [
            Citation(
                citation_id=f"chunk:{chunk.id}",
                chunk_id=chunk.id,
                document_id=document.id,
                document_version_id=version.id,
                document_name=document.name,
                section_heading=section.heading,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                excerpt=evidence.excerpt,
            )
            for evidence, chunk, section, version, document in rows
        ]

    def _count(self, statement: Any) -> int:
        return int(
            self._session.scalar(select(func.count()).select_from(statement.subquery())) or 0
        )

    @staticmethod
    def _require_engineer(access: ProjectAccess) -> None:
        if access.role not in {
            MembershipRole.ENGINEER,
            MembershipRole.REVIEWER,
            MembershipRole.ADMIN,
        }:
            raise ApplicationError(
                "PROJECT_WRITE_FORBIDDEN", "Engineer-level project access is required.", 403
            )

    @staticmethod
    def _require_admin(access: ProjectAccess) -> None:
        if access.role is not MembershipRole.ADMIN:
            raise ApplicationError(
                "PROJECT_ADMIN_REQUIRED", "Admin project access is required.", 403
            )
