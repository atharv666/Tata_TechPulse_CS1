"""MVP resource routes. Handlers only validate transport data and delegate to MvpApiService."""

from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy.orm import Session

from app.api.dependencies import CurrentUser, ProjectAccess, get_current_user, project_access
from app.core.metrics import metrics
from app.db.session import get_db_session
from app.schemas.api import (
    ComparisonFindingResponse,
    ComparisonRequest,
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
from app.services.api import MvpApiService

router = APIRouter()


@router.get("/metrics")
def get_system_metrics() -> dict[str, object]:
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


@router.post("/projects/{project_id}/members", status_code=status.HTTP_201_CREATED)
def add_member(
    request: MemberCreate, scoped: tuple[ProjectAccess, MvpApiService] = Depends(project_service)
) -> object:
    access, app = scoped
    return app.add_member(access, request)


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
    page: Page = Depends(), scoped: tuple[ProjectAccess, MvpApiService] = Depends(project_service)
) -> PageResponse:
    access, app = scoped
    items, total = app.entities(access, page.offset, page.limit)
    return PageResponse(
        items=[EntityResponse.model_validate(item, from_attributes=True) for item in items],
        **page.model_dump(),
        total=total,
    )


@router.get("/projects/{project_id}/relationships", response_model=PageResponse)
def list_relationships(
    page: Page = Depends(), scoped: tuple[ProjectAccess, MvpApiService] = Depends(project_service)
) -> PageResponse:
    access, app = scoped
    items, total = app.relationships(access, page.offset, page.limit)
    return PageResponse(
        items=[RelationshipResponse.model_validate(item, from_attributes=True) for item in items],
        **page.model_dump(),
        total=total,
    )


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


@router.post("/projects/{project_id}/query")
async def query(
    request: QueryRequest, scoped: tuple[ProjectAccess, MvpApiService] = Depends(project_service)
) -> object:
    access, app = scoped
    return await app.query(access, request)


@router.post("/projects/{project_id}/impact")
def impact(
    request: ImpactRequest, scoped: tuple[ProjectAccess, MvpApiService] = Depends(project_service)
) -> object:
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
    access, app = scoped
    _, job = app.comparison(access, request)
    return JobResponse.model_validate(job, from_attributes=True)


@router.get(
    "/projects/{project_id}/comparisons/{comparison_id}/findings",
    response_model=PageResponse,
)
def list_comparison_findings(
    comparison_id: UUID,
    page: Page = Depends(),
    scoped: tuple[ProjectAccess, MvpApiService] = Depends(project_service),
) -> PageResponse:
    access, app = scoped
    items, total = app.comparison_findings(access, comparison_id, page.offset, page.limit)
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
    return PageResponse(items=items, **page.model_dump(), total=total)
