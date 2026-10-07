"""HTTP integration tests for routing, request IDs, pagination, and project isolation boundaries."""

from types import SimpleNamespace
from uuid import uuid4

from app.api.dependencies import ProjectAccess
from app.api.routes.mvp import project_service, service
from app.db.session import get_db_session
from app.main import create_application
from app.models.enums import MembershipRole
from fastapi.testclient import TestClient


class FakeService:
    def __init__(self) -> None:
        self.project = SimpleNamespace(id=uuid4(), name="Brake", description="HLD")

    def create_project(self, request: object) -> object:
        return self.project

    def projects(self, offset: int, limit: int) -> tuple[list[object], int]:
        return [self.project], 1

    def documents(
        self, access: object, offset: int, limit: int
    ) -> tuple[list[object], int]:
        return [], 0

    def upload_document_content(
        self, access: object, filename: str, media_type: str | None, content: bytes
    ) -> object:
        assert filename == "architecture.md"
        assert media_type == "text/markdown"
        assert content == b"# Architecture"
        return SimpleNamespace(
            id=uuid4(), job_type="DOCUMENT_INGESTION", state="PENDING", details={}
        )

    def reembed(self, access: object) -> object:
        return SimpleNamespace(
            id=uuid4(), job_type="REEMBED", state="PENDING", details={}
        )


def test_health_includes_a_request_id() -> None:
    with TestClient(create_application()) as client:
        response = client.get("/api/v1/health", headers={"X-Request-Id": "request-123"})

    assert response.status_code == 200
    assert response.headers["X-Request-Id"] == "request-123"


def test_project_creation_and_paginated_listing_delegate_to_service() -> None:
    application = create_application()
    fake = FakeService()
    application.dependency_overrides[service] = lambda: fake
    with TestClient(application) as client:
        created = client.post(
            "/api/v1/projects",
            headers={"X-User-Id": "engineer"},
            json={"name": "Brake"},
        )
        listed = client.get(
            "/api/v1/projects?offset=0&limit=10", headers={"X-User-Id": "engineer"}
        )

    assert created.status_code == 201
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["name"] == "Brake"


def test_project_scoped_routes_receive_authorized_context_and_reject_non_members() -> (
    None
):
    project = uuid4()
    application = create_application()
    fake = FakeService()
    access = ProjectAccess(project, "member", MembershipRole.VIEWER)
    application.dependency_overrides[project_service] = lambda: (access, fake)
    with TestClient(application) as client:
        allowed = client.get(
            f"/api/v1/projects/{project}/documents", headers={"X-User-Id": "member"}
        )

    assert allowed.status_code == 200
    assert allowed.json()["items"] == []

    class NoMembershipSession:
        def scalar(self, statement: object) -> None:
            return None

    denied_application = create_application()
    denied_application.dependency_overrides[get_db_session] = lambda: (
        NoMembershipSession()
    )
    with TestClient(denied_application) as client:
        denied = client.get(
            f"/api/v1/projects/{project}/documents", headers={"X-User-Id": "outsider"}
        )

    assert denied.status_code == 403
    assert denied.json()["code"] == "PROJECT_ACCESS_DENIED"


def test_missing_development_identity_returns_consistent_error() -> None:
    application = create_application()
    application.dependency_overrides[get_db_session] = lambda: SimpleNamespace()
    with TestClient(application) as client:
        response = client.get(f"/api/v1/projects/{uuid4()}/documents")

    assert response.status_code == 401
    assert response.json()["code"] == "AUTHENTICATION_REQUIRED"


def test_multipart_document_upload_delegates_private_content_to_service() -> None:
    project = uuid4()
    application = create_application()
    fake = FakeService()
    access = ProjectAccess(project, "member", MembershipRole.ENGINEER)
    application.dependency_overrides[project_service] = lambda: (access, fake)

    with TestClient(application) as client:
        response = client.post(
            f"/api/v1/projects/{project}/documents/upload",
            headers={"X-User-Id": "member"},
            files={"file": ("architecture.md", b"# Architecture", "text/markdown")},
        )

    assert response.status_code == 202
    assert response.json()["job_type"] == "DOCUMENT_INGESTION"


def test_reembed_is_a_project_scoped_background_job() -> None:
    project = uuid4()
    application = create_application()
    fake = FakeService()
    access = ProjectAccess(project, "engineer", MembershipRole.ENGINEER)
    application.dependency_overrides[project_service] = lambda: (access, fake)

    with TestClient(application) as client:
        response = client.post(f"/api/v1/projects/{project}/reembed")

    assert response.status_code == 202
    assert response.json()["job_type"] == "REEMBED"
