"""MVP resource routes. Handlers only validate transport data and delegate to MvpApiService."""

from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentUser, ProjectAccess, get_current_user, project_access
from app.core.metrics import metrics
from app.db.session import get_db_session
from app.models.enums import ValidationState
from app.retrieval.evidence import GroundedAnswer
from app.retrieval.impact import ImpactAnalysisResult
from app.schemas.api import (
    ComparisonDetail,
    ComparisonFindingResponse,
    ComparisonRequest,
    ComparisonResponse,
    DocumentResponse,
    DocumentUploadRequest,
    DocumentVersionResponse,
    EntityCorrection,
    EntityResponse,
    ImpactRequest,
    JobResponse,
    MemberCreate,
    Page,
    PageResponse,
    ProjectCreate,
    ProjectResponse,
    QueryRequest,
    RelationshipCorrection,
    RelationshipResponse,
    ReviewDecision,
)
from app.schemas.graph import (
    DismissRequest,
    EntityDetail,
    EntityReport,
    FindingResponse,
    MemberResponse,
    RelationshipDetail,
    UndoMergeRequest,
)
from app.schemas.review import AuditEventDisplay
from app.services.api import MvpApiService
from app.services.export import ExportService
from app.services.knowledge import finding_response

router = APIRouter()


@router.get("/metrics")
def get_system_metrics(_: CurrentUser = Depends(get_current_user)) -> dict[str, object]:
    """Process counters; operational data is never served to anonymous callers."""
    return metrics.snapshot()


def service(
    session: Session = Depends(get_db_session), user: CurrentUser = Depends(get_current_user)
) -> MvpApiService:
    return MvpApiService(session, user)


def project_service(
    access: ProjectAccess = Depends(project_access), app: MvpApiService = Depends(service)
) -> tuple[ProjectAccess, MvpApiService]:
    return access, app


@router.post("/projects", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(request: ProjectCreate, app: MvpApiService = Depends(service)) -> object:
    return app.create_project(request)


@router.get("/projects", response_model=PageResponse)
def list_projects(page: Page = Depends(), app: MvpApiService = Depends(service)) -> PageResponse:
    items, total = app.projects(page.offset, page.limit)
    return PageResponse(
        items=[ProjectResponse.model_validate(item, from_attributes=True) for item in items],
        **page.model_dump(),
        total=total,
    )


@router.post(
    "/projects/{project_id}/members",
    response_model=MemberResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_member(
    request: MemberCreate, scoped: tuple[ProjectAccess, MvpApiService] = Depends(project_service)
) -> MemberResponse:
    access, app = scoped
    member = app.add_member(access, request)
    return MemberResponse(user_id=member.user_id, role=member.role.value)


@router.post(
    "/projects/{project_id}/documents",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def upload_document(
    request: DocumentUploadRequest,
    scoped: tuple[ProjectAccess, MvpApiService] = Depends(project_service),
) -> JobResponse:
    access, app = scoped
    job = app.upload_document(access, request)
    return JobResponse.model_validate(job, from_attributes=True)


@router.post(
    "/projects/{project_id}/documents/upload",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document_file(
    file: UploadFile = File(...),
    scoped: tuple[ProjectAccess, MvpApiService] = Depends(project_service),
) -> JobResponse:
    """Accept a browser/API file upload; its filename never controls storage paths."""
    access, app = scoped
    content = await file.read()
    job = app.upload_document_content(access, file.filename or "upload", file.content_type, content)
    return JobResponse.model_validate(job, from_attributes=True)


@router.get("/projects/{project_id}/documents", response_model=PageResponse)
def list_documents(
    page: Page = Depends(), scoped: tuple[ProjectAccess, MvpApiService] = Depends(project_service)
) -> PageResponse:
    access, app = scoped
    items, total = app.documents(access, page.offset, page.limit)
    return PageResponse(
        items=[DocumentResponse.model_validate(item, from_attributes=True) for item in items],
        **page.model_dump(),
        total=total,
    )


@router.get("/projects/{project_id}/documents/{document_id}/versions", response_model=PageResponse)
def list_versions(
    document_id: UUID,
    page: Page = Depends(),
    scoped: tuple[ProjectAccess, MvpApiService] = Depends(project_service),
) -> PageResponse:
    access, app = scoped
    items, total = app.document_versions(access, document_id, page.offset, page.limit)
    return PageResponse(
        items=[
            DocumentVersionResponse.model_validate(item, from_attributes=True) for item in items
        ],
        **page.model_dump(),
        total=total,
    )


@router.get("/projects/{project_id}/jobs", response_model=PageResponse)
def list_jobs(
    page: Page = Depends(), scoped: tuple[ProjectAccess, MvpApiService] = Depends(project_service)
) -> PageResponse:
    access, app = scoped
    items, total = app.jobs(access, page.offset, page.limit)
    return PageResponse(
        items=[JobResponse.model_validate(item, from_attributes=True) for item in items],
        **page.model_dump(),
        total=total,
    )


@router.post("/projects/{project_id}/jobs/{job_id}/cancel", response_model=JobResponse)
def cancel_job(
    job_id: UUID,
    scoped: tuple[ProjectAccess, MvpApiService] = Depends(project_service),
) -> JobResponse:
    access, app = scoped
    return JobResponse.model_validate(app.cancel_job(access, job_id), from_attributes=True)


@router.get("/projects/{project_id}/entities", response_model=PageResponse)
def list_entities(
    page: Page = Depends(),
    entity_type: str | None = None,
    validation_state: ValidationState | None = None,
    q: str | None = Query(default=None, max_length=200),
    scoped: tuple[ProjectAccess, MvpApiService] = Depends(project_service),
) -> PageResponse:
    """Live entities only (merged and replaced ones are reachable through their detail view)."""
    access, app = scoped
    items, total = app.entities(
        access,
        page.offset,
        page.limit,
        entity_type=entity_type,
        validation_state=validation_state.value if validation_state else None,
        query=q,
    )
    return PageResponse(
        items=[EntityResponse.model_validate(item, from_attributes=True) for item in items],
        **page.model_dump(),
        total=total,
    )


@router.get("/projects/{project_id}/entities/{entity_id}", response_model=EntityDetail)
def entity_detail(
    entity_id: UUID, scoped: tuple[ProjectAccess, MvpApiService] = Depends(project_service)
) -> EntityDetail:
    """Everything a reviewer needs: aliases, merged duplicates, evidence, history, findings."""
    access, app = scoped
    return app.knowledge(access).entity_detail(entity_id)


@router.get("/projects/{project_id}/relationships", response_model=PageResponse)
def list_relationships(
    page: Page = Depends(),
    relationship_type: str | None = None,
    entity_id: UUID | None = None,
    scoped: tuple[ProjectAccess, MvpApiService] = Depends(project_service),
) -> PageResponse:
    access, app = scoped
    items, total = app.relationships(
        access,
        page.offset,
        page.limit,
        relationship_type=relationship_type,
        entity_id=entity_id,
    )
    return PageResponse(
        items=[RelationshipResponse.model_validate(item, from_attributes=True) for item in items],
        **page.model_dump(),
        total=total,
    )


@router.get(
    "/projects/{project_id}/relationships/{relationship_id}", response_model=RelationshipDetail
)
def relationship_detail(
    relationship_id: UUID, scoped: tuple[ProjectAccess, MvpApiService] = Depends(project_service)
) -> RelationshipDetail:
    access, app = scoped
    return app.knowledge(access).relationship_detail(relationship_id)


@router.get("/projects/{project_id}/entities/{entity_id}/report", response_model=EntityReport)
def entity_report(
    entity_id: UUID, scoped: tuple[ProjectAccess, MvpApiService] = Depends(project_service)
) -> EntityReport:
    """What the graph states about one component/interface/signal/flow, with sources."""
    access, app = scoped
    return app.knowledge(access).entity_report(entity_id)


@router.get("/projects/{project_id}/export")
def export_knowledge(
    format: str = Query(default="json", pattern="^(json|csv|xlsx)$"),
    table: str = Query(
        default="entities", pattern="^(entities|relationships|findings|components)$"
    ),
    include_rejected: bool = False,
    scoped: tuple[ProjectAccess, MvpApiService] = Depends(project_service),
) -> Response:
    """Structured output of the knowledge graph with provenance (JSON, CSV or XLSX)."""
    access, app = scoped
    exporter = ExportService(app.session, access.project_id)
    if format == "csv":
        return Response(
            exporter.to_csv(table, include_rejected),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{table}.csv"'},
        )
    if format == "xlsx":
        return Response(
            exporter.to_xlsx(include_rejected),
            media_type=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            headers={"Content-Disposition": 'attachment; filename="architecture.xlsx"'},
        )
    return JSONResponse(
        exporter.to_json(include_rejected),
        headers={"Content-Disposition": 'attachment; filename="architecture.json"'},
    )


@router.get("/projects/{project_id}/findings", response_model=PageResponse)
def list_findings(
    page: Page = Depends(),
    status_filter: str | None = Query(
        default=None, alias="status", pattern="^(OPEN|DISMISSED|RESOLVED)$"
    ),
    finding_type: str | None = Query(default=None, max_length=64),
    scoped: tuple[ProjectAccess, MvpApiService] = Depends(project_service),
) -> PageResponse:
    """Potential inconsistencies detected by the graph build, most severe first."""
    access, app = scoped
    rows, total = app.findings(access).list(
        status=status_filter, finding_type=finding_type, limit=page.limit, offset=page.offset
    )
    return PageResponse(
        items=[finding_response(row) for row in rows], **page.model_dump(), total=total
    )


@router.post("/projects/{project_id}/findings/{finding_id}/dismiss", response_model=FindingResponse)
def dismiss_finding(
    finding_id: UUID,
    request: DismissRequest,
    scoped: tuple[ProjectAccess, MvpApiService] = Depends(project_service),
) -> FindingResponse:
    access, app = scoped
    app.require_reviewer(access)
    return finding_response(app.findings(access).dismiss(finding_id, request.reason))


@router.post("/projects/{project_id}/findings/{finding_id}/reopen", response_model=FindingResponse)
def reopen_finding(
    finding_id: UUID, scoped: tuple[ProjectAccess, MvpApiService] = Depends(project_service)
) -> FindingResponse:
    access, app = scoped
    app.require_reviewer(access)
    return finding_response(app.findings(access).reopen(finding_id))


@router.get("/projects/{project_id}/merges", response_model=PageResponse)
def list_merges(
    page: Page = Depends(),
    include_undone: bool = True,
    scoped: tuple[ProjectAccess, MvpApiService] = Depends(project_service),
) -> PageResponse:
    """Which entities were merged, by which rule or model, and why (the merge audit log)."""
    access, app = scoped
    items, total = app.knowledge(access).merges(
        page.offset, page.limit, include_undone=include_undone
    )
    return PageResponse(items=items, **page.model_dump(), total=total)


@router.post(
    "/projects/{project_id}/merges/{merge_id}/undo", status_code=status.HTTP_204_NO_CONTENT
)
def undo_entity_merge(
    merge_id: UUID,
    request: UndoMergeRequest,
    scoped: tuple[ProjectAccess, MvpApiService] = Depends(project_service),
) -> None:
    """Reverse a merge; the pair is remembered as 'different' and is not merged again."""
    access, app = scoped
    app.knowledge(access).undo_merge(merge_id, request.reason)


@router.post(
    "/projects/{project_id}/graph-build",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def build_graph(
    scoped: tuple[ProjectAccess, MvpApiService] = Depends(project_service),
) -> JobResponse:
    access, app = scoped
    return JobResponse.model_validate(app.graph_build(access), from_attributes=True)


@router.post(
    "/projects/{project_id}/reembed",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def reembed_project(
    scoped: tuple[ProjectAccess, MvpApiService] = Depends(project_service),
) -> JobResponse:
    """Explicitly re-index only the requesting project with the selected model."""
    access, app = scoped
    return JobResponse.model_validate(app.reembed(access), from_attributes=True)


@router.get("/projects/{project_id}/review-queue", response_model=PageResponse)
def review_queue(
    page: Page = Depends(), scoped: tuple[ProjectAccess, MvpApiService] = Depends(project_service)
) -> PageResponse:
    access, app = scoped
    items = app.review(access).review_queue()
    return PageResponse(
        items=items[page.offset : page.offset + page.limit], **page.model_dump(), total=len(items)
    )


@router.post("/projects/{project_id}/entities/{entity_id}/verify", response_model=EntityResponse)
def verify_entity(
    entity_id: UUID,
    request: ReviewDecision,
    scoped: tuple[ProjectAccess, MvpApiService] = Depends(project_service),
) -> object:
    access, app = scoped
    return app.review(access).verify_entity(entity_id, request.reason)


@router.post("/projects/{project_id}/entities/{entity_id}/correct", response_model=EntityResponse)
def correct_entity(
    entity_id: UUID,
    request: EntityCorrection,
    scoped: tuple[ProjectAccess, MvpApiService] = Depends(project_service),
) -> object:
    access, app = scoped
    return app.review(access).correct_entity(
        entity_id, request.canonical_name, request.entity_type, request.reason
    )


@router.post("/projects/{project_id}/entities/{entity_id}/reject", response_model=EntityResponse)
def reject_entity(
    entity_id: UUID,
    request: ReviewDecision,
    scoped: tuple[ProjectAccess, MvpApiService] = Depends(project_service),
) -> object:
    access, app = scoped
    if request.reason is None:
        raise ValueError("A rejection reason is required.")
    return app.review(access).reject_entity(entity_id, request.reason)


@router.post(
    "/projects/{project_id}/relationships/{relationship_id}/verify",
    response_model=RelationshipResponse,
)
def verify_relationship(
    relationship_id: UUID,
    request: ReviewDecision,
    scoped: tuple[ProjectAccess, MvpApiService] = Depends(project_service),
) -> object:
    access, app = scoped
    return app.review(access).verify_relationship(relationship_id, request.reason)


@router.post(
    "/projects/{project_id}/relationships/{relationship_id}/correct",
    response_model=RelationshipResponse,
)
def correct_relationship(
    relationship_id: UUID,
    request: RelationshipCorrection,
    scoped: tuple[ProjectAccess, MvpApiService] = Depends(project_service),
) -> object:
    access, app = scoped
    return app.review(access).correct_relationship(
        relationship_id,
        request.source_entity_id,
        request.target_entity_id,
        request.relationship_type,
        request.reason,
    )


@router.post(
    "/projects/{project_id}/relationships/{relationship_id}/reject",
    response_model=RelationshipResponse,
)
def reject_relationship(
    relationship_id: UUID,
    request: ReviewDecision,
    scoped: tuple[ProjectAccess, MvpApiService] = Depends(project_service),
) -> object:
    access, app = scoped
    if request.reason is None:
        raise ValueError("A rejection reason is required.")
    return app.review(access).reject_relationship(relationship_id, request.reason)


@router.post("/projects/{project_id}/query", response_model=GroundedAnswer)
async def query(
    request: QueryRequest, scoped: tuple[ProjectAccess, MvpApiService] = Depends(project_service)
) -> GroundedAnswer:
    access, app = scoped
    return await app.query(access, request)


@router.post("/projects/{project_id}/impact", response_model=ImpactAnalysisResult)
def impact(
    request: ImpactRequest, scoped: tuple[ProjectAccess, MvpApiService] = Depends(project_service)
) -> ImpactAnalysisResult:
    access, app = scoped
    return app.impact(access, request)


@router.post(
    "/projects/{project_id}/comparisons",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def compare_revisions(
    request: ComparisonRequest,
    scoped: tuple[ProjectAccess, MvpApiService] = Depends(project_service),
) -> JobResponse:
    """Queue a comparison; ``details.payload.comparison_id`` identifies it for later reads."""
    access, app = scoped
    _, job = app.comparison(access, request)
    return JobResponse.model_validate(job, from_attributes=True)


@router.get("/projects/{project_id}/comparisons", response_model=PageResponse)
def list_comparisons(
    page: Page = Depends(), scoped: tuple[ProjectAccess, MvpApiService] = Depends(project_service)
) -> PageResponse:
    access, app = scoped
    items, total = app.comparisons(access, page.offset, page.limit)
    return PageResponse(
        items=[ComparisonResponse.model_validate(item, from_attributes=True) for item in items],
        **page.model_dump(),
        total=total,
    )


@router.get("/projects/{project_id}/comparisons/{comparison_id}", response_model=ComparisonDetail)
def get_comparison(
    comparison_id: UUID, scoped: tuple[ProjectAccess, MvpApiService] = Depends(project_service)
) -> ComparisonDetail:
    access, app = scoped
    comparison, summary = app.get_comparison(access, comparison_id)
    return ComparisonDetail(
        **ComparisonResponse.model_validate(comparison, from_attributes=True).model_dump(),
        summary=summary,
        finding_count=sum(summary.values()),
    )


@router.get(
    "/projects/{project_id}/comparisons/{comparison_id}/findings",
    response_model=PageResponse,
)
def list_comparison_findings(
    comparison_id: UUID,
    page: Page = Depends(),
    classification: str | None = Query(default=None, max_length=64),
    scoped: tuple[ProjectAccess, MvpApiService] = Depends(project_service),
) -> PageResponse:
    access, app = scoped
    items, total = app.comparison_findings(
        access, comparison_id, page.offset, page.limit, classification
    )
    return PageResponse(
        items=[
            ComparisonFindingResponse.model_validate(item, from_attributes=True) for item in items
        ],
        **page.model_dump(),
        total=total,
    )


@router.get("/projects/{project_id}/audit", response_model=PageResponse)
def audit(
    page: Page = Depends(), scoped: tuple[ProjectAccess, MvpApiService] = Depends(project_service)
) -> PageResponse:
    access, app = scoped
    items, total = app.audit(access, page.offset, page.limit)
    return PageResponse(
        items=[AuditEventDisplay.model_validate(item, from_attributes=True) for item in items],
        **page.model_dump(),
        total=total,
    )


@router.get("/projects/{project_id}/members", response_model=PageResponse)
def list_members(
    page: Page = Depends(), scoped: tuple[ProjectAccess, MvpApiService] = Depends(project_service)
) -> PageResponse:
    access, app = scoped
    items, total = app.members(access, page.offset, page.limit)
    return PageResponse(
        items=[MemberResponse(user_id=item.user_id, role=item.role.value) for item in items],
        **page.model_dump(),
        total=total,
    )
