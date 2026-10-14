"""Thin application service facade used by HTTP routes; domain rules remain in domain services."""

from __future__ import annotations

import base64
import hashlib
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentUser, ProjectAccess
from app.core.config import get_settings
from app.core.errors import ApplicationError, NotFoundError
from app.ingestion.contracts import IngestionError
from app.ingestion.validation import validate_upload
from app.jobs.source_store import SourceStore
from app.models.enums import ComparisonState, MembershipRole
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
from app.retrieval.answer import RagPipeline
from app.retrieval.evidence import GroundedAnswer
from app.retrieval.impact import ImpactAnalysisResult, ImpactAnalysisService
from app.retrieval.vector import EmbeddingService
from app.schemas.api import (
    ComparisonRequest,
    DocumentUploadRequest,
    ImpactRequest,
    MemberCreate,
    ProjectCreate,
    QueryRequest,
)
from app.services.findings import FindingsService
from app.services.knowledge import KnowledgeService
from app.services.review import ReviewActor, ReviewService


class MvpApiService:
    def __init__(self, session: Session, user: CurrentUser) -> None:
        self._session = session
        self._user = user

    @property
    def session(self) -> Session:
        return self._session

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

    def members(
        self, access: ProjectAccess, offset: int, limit: int
    ) -> tuple[list[ProjectMember], int]:
        self._require_admin(access)
        statement = (
            select(ProjectMember)
            .where(ProjectMember.project_id == access.project_id)
            .order_by(ProjectMember.user_id)
        )
        return list(self._session.scalars(statement.offset(offset).limit(limit))), self._count(
            statement
        )

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

    def knowledge(self, access: ProjectAccess) -> KnowledgeService:
        return KnowledgeService(self._session, access)

    def findings(self, access: ProjectAccess) -> FindingsService:
        return FindingsService(self._session, access.project_id, access.user_id)

    def entities(
        self, access: ProjectAccess, offset: int, limit: int, **filters: Any
    ) -> tuple[list[Entity], int]:
        return self.knowledge(access).entities(offset, limit, **filters)

    def relationships(
        self, access: ProjectAccess, offset: int, limit: int, **filters: Any
    ) -> tuple[list[Relationship], int]:
        return self.knowledge(access).relationships(offset, limit, **filters)

    def graph_build(self, access: ProjectAccess) -> Job:
        self._require_engineer(access)
        return JobRepository(self._session).enqueue(
            access.project_id,
            "GRAPH_BUILD",
            access.user_id,
            {"resolve": True},
            f"graph-build:{access.project_id}:manual",
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

    async def query(self, access: ProjectAccess, request: QueryRequest) -> GroundedAnswer:
        """Answer a question from the project's documents. Read-only: it never mutates the graph."""
        settings = get_settings()
        embeddings = EmbeddingService(
            create_embedding_provider(settings.embedding_settings()), settings.embedding_settings()
        )
        pipeline = RagPipeline(
            self._session,
            access.project_id,
            embeddings,
            create_llm_provider(settings.llm_settings()),
            settings,
        )
        versions = [request.document_version_id] if request.document_version_id else None
        outcome = await pipeline.answer(
            request.query,
            document_version_ids=versions,
            top_k=request.top_k,
            mode=request.mode,
        )
        return outcome.answer

    def impact(self, access: ProjectAccess, request: ImpactRequest) -> ImpactAnalysisResult:
        """Potentially affected elements for a change to one entity (read-only, bounded)."""
        return ImpactAnalysisService(self._session, access.project_id).analyze(
            request.root_entity_id,
            request.document_version_id,
            request.depth,
            request.node_limit,
            request.edge_limit,
        )

    def comparison(
        self, access: ProjectAccess, request: ComparisonRequest
    ) -> tuple[Comparison, Job]:
        """Queue a comparison of two document versions (the worker computes the findings)."""
        self._require_engineer(access)
        if request.base_version_id == request.target_version_id:
            raise ValueError("Comparison requires two distinct document versions.")
        repository = ComparisonRepository(self._session, access.project_id)
        repository.require_version(request.base_version_id)
        repository.require_version(request.target_version_id)
        comparison = Comparison(
            project_id=access.project_id,
            base_version_id=request.base_version_id,
            target_version_id=request.target_version_id,
            requested_by=access.user_id,
            state=ComparisonState.PENDING,
        )
        repository.add_comparison(comparison)
        self._session.flush()
        job = JobRepository(self._session).enqueue(
            access.project_id,
            "REVISION_COMPARISON",
            access.user_id,
            {
                "comparison_id": str(comparison.id),
                "base_version_id": str(request.base_version_id),
                "target_version_id": str(request.target_version_id),
            },
            f"comparison:{comparison.id}",
        )
        return comparison, job

    def comparisons(
        self, access: ProjectAccess, offset: int, limit: int
    ) -> tuple[list[Comparison], int]:
        statement = (
            select(Comparison)
            .where(Comparison.project_id == access.project_id)
            .order_by(Comparison.created_at.desc(), Comparison.id)
        )
        return list(self._session.scalars(statement.offset(offset).limit(limit))), self._count(
            statement
        )

    def get_comparison(
        self, access: ProjectAccess, comparison_id: UUID
    ) -> tuple[Comparison, dict[str, int]]:
        comparison = self._session.scalar(
            select(Comparison).where(
                Comparison.project_id == access.project_id, Comparison.id == comparison_id
            )
        )
        if comparison is None:
            raise NotFoundError("COMPARISON_NOT_FOUND", "Comparison was not found in this project.")
        rows = self._session.execute(
            select(ComparisonFinding.finding_type, func.count(ComparisonFinding.id))
            .where(ComparisonFinding.comparison_id == comparison.id)
            .group_by(ComparisonFinding.finding_type)
        )
        return comparison, {kind: int(total) for kind, total in rows}

    def comparison_findings(
        self,
        access: ProjectAccess,
        comparison_id: UUID,
        offset: int,
        limit: int,
        classification: str | None = None,
    ) -> tuple[list[ComparisonFinding], int]:
        self.get_comparison(access, comparison_id)  # 404 for a comparison of another project
        conditions = [
            ComparisonFinding.project_id == access.project_id,
            ComparisonFinding.comparison_id == comparison_id,
        ]
        if classification:
            conditions.append(ComparisonFinding.finding_type == classification)
        statement = (
            select(ComparisonFinding)
            .where(*conditions)
            .order_by(ComparisonFinding.created_at, ComparisonFinding.id)
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
    def require_reviewer(access: ProjectAccess) -> None:
        if access.role not in {MembershipRole.REVIEWER, MembershipRole.ADMIN}:
            raise ApplicationError(
                "PROJECT_REVIEW_FORBIDDEN", "Reviewer-level project access is required.", 403
            )

    @staticmethod
    def _require_admin(access: ProjectAccess) -> None:
        if access.role is not MembershipRole.ADMIN:
            raise ApplicationError(
                "PROJECT_ADMIN_REQUIRED", "Admin project access is required.", 403
            )
