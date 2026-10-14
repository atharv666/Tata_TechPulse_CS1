"""OCR through the real ingestion service and database: flags, cache, audit and consent."""

from __future__ import annotations

import pytest
from app.core.config import get_settings
from app.db.session import get_session_factory
from app.ingestion.service import IngestionService, Upload
from app.models.schema import AuditEvent, Chunk, DocumentVersion, OcrCache
from sqlalchemy import func, select

from tests.support.documents import make_scanned_pdf
from tests.support.pipeline import create_project
from tests.test_ocr import FakeOCR

pytestmark = pytest.mark.integration


def ingest(
    access, ocr, name: str = "scan.pdf", content: bytes | None = None, settings=None
):
    service = IngestionService(settings or get_settings(), ocr_provider=ocr)
    with get_session_factory()() as session:
        result = service.ingest(
            session,
            access.project_id,
            access.user_id,
            Upload(
                name, "application/pdf", content or make_scanned_pdf(), "managed://t"
            ),
        )
        session.commit()
        return result.version.id


def test_ocr_chunks_are_flagged_and_the_page_is_recorded(clean_database) -> None:
    access = create_project()
    version_id = ingest(access, FakeOCR())

    with get_session_factory()() as session:
        chunks = list(
            session.scalars(
                select(Chunk).where(Chunk.document_version_id == version_id)
            )
        )
        version = session.get(DocumentVersion, version_id)
        assert chunks and all(
            c.chunk_kind == "OCR_TEXT" and c.attrs["ocr"] for c in chunks
        )
        assert all(c.page_start == c.page_end == 1 for c in chunks)
        assert version is not None and version.properties["ocr_pages"] == [1]


def test_external_ocr_use_is_audited_with_counts_only(clean_database) -> None:
    access = create_project()
    ingest(access, FakeOCR(external=True))

    with get_session_factory()() as session:
        event = session.scalar(
            select(AuditEvent).where(AuditEvent.action == "EXTERNAL_OCR_USED")
        )
        assert event is not None
        assert event.details == {
            "provider": "fake-ocr",
            "pages": 1,
        }  # never page content
        assert event.actor_id == "alice"


def test_local_ocr_is_not_reported_as_external_use(clean_database) -> None:
    access = create_project()
    ingest(access, FakeOCR(external=False))

    with get_session_factory()() as session:
        count = session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.action == "EXTERNAL_OCR_USED")
        )
        assert count == 0


def test_page_cache_prevents_a_second_provider_call_for_the_same_image(
    clean_database,
) -> None:
    access = create_project()
    first, second = FakeOCR(external=True), FakeOCR(external=True)
    pdf = make_scanned_pdf()

    ingest(access, first, name="a.pdf", content=pdf)
    # the same scan is uploaded again under another name but with different PDF bytes
    import fitz

    document = fitz.open(stream=pdf, filetype="pdf")
    document.set_metadata({"title": "second upload"})
    ingest(access, second, name="b.pdf", content=document.tobytes())

    assert first.calls == 1 and second.calls == 0  # the image was recognised once
    with get_session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(OcrCache)) == 1


def test_a_refused_external_provider_still_ingests_the_document_with_a_clear_warning(
    clean_database,
) -> None:
    access = create_project()
    settings = get_settings().model_copy(
        update={"ocr_provider": "gemini", "ocr_model": "m", "ocr_allow_external": False}
    )
    version_id = ingest(access, None, settings=settings)

    with get_session_factory()() as session:
        version = session.get(DocumentVersion, version_id)
        assert version is not None
        assert version.properties["ocr_pages"] == []
        assert any("OCR_ALLOW_EXTERNAL" in w for w in version.properties["warnings"])
