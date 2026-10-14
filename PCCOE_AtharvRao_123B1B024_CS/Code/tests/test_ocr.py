"""OCR: parser integration, provider adapters (no network), consent gate, cache and audit."""

from __future__ import annotations

import base64
import json

import fitz
import httpx
import pytest
from app.core.config import get_settings
from app.ingestion.normalize import normalize_document
from app.ingestion.ocr import (
    OCR_PROMPT,
    CachingOCRProvider,
    GeminiVisionOCRProvider,
    OCRUnavailableError,
    RefusingOCRProvider,
    TesseractOCRProvider,
    create_ocr_provider,
)
from app.ingestion.parsers import OCRProvider, PDFParser

from tests.support.documents import make_nested_pdf, make_scanned_pdf


class FakeOCR(OCRProvider):
    name = "fake-ocr"

    def __init__(
        self, external: bool = False, text: str = "BrakeController requires X."
    ) -> None:
        self.external = external
        self.text = text
        self.calls = 0

    def extract_text(self, image_bytes: bytes, page_number: int) -> str:
        assert image_bytes.startswith(b"\x89PNG")  # a rendered page image
        self.calls += 1
        return f"{self.text}\n\nSecond paragraph on page {page_number}."


def two_scanned_pages() -> bytes:
    document = fitz.open()
    for _ in range(2):
        document.insert_pdf(fitz.open(stream=make_scanned_pdf(), filetype="pdf"))
    return document.tobytes()


# ---- parser behaviour -------------------------------------------------------------------------
def test_scanned_page_is_recovered_through_the_provider_and_flagged() -> None:
    ocr = FakeOCR()
    parsed = PDFParser(ocr).parse(make_scanned_pdf())

    assert parsed.ocr_pages == [1] and ocr.calls == 1
    assert [b.text for b in parsed.blocks] == [
        "BrakeController requires X.",
        "Second paragraph on page 1.",
    ]
    assert all(b.ocr and b.position.page == 1 for b in parsed.blocks)


def test_scanned_page_without_a_provider_warns_instead_of_silently_losing_the_page() -> (
    None
):
    parsed = PDFParser(None).parse(make_scanned_pdf())

    assert parsed.blocks == [] and parsed.ocr_pages == []
    assert any("no extractable text" in warning for warning in parsed.warnings)


def test_pages_with_a_text_layer_are_never_sent_to_ocr() -> None:
    ocr = FakeOCR()
    PDFParser(ocr).parse(make_nested_pdf())
    assert ocr.calls == 0


def test_ocr_page_budget_is_enforced_with_a_warning() -> None:
    ocr = FakeOCR()
    parsed = PDFParser(ocr, ocr_max_pages=1).parse(two_scanned_pages())

    assert parsed.ocr_pages == [1] and ocr.calls == 1
    assert any("budget is exhausted" in warning for warning in parsed.warnings)


def test_provider_failure_is_reported_with_its_safe_reason() -> None:
    parsed = PDFParser(RefusingOCRProvider("External OCR is disabled.")).parse(
        make_scanned_pdf()
    )
    assert any("External OCR is disabled." in warning for warning in parsed.warnings)


def test_ocr_text_flows_into_sections_and_chunks_with_the_ocr_flag() -> None:
    from app.ingestion.chunking import plan_document

    parsed = PDFParser(FakeOCR()).parse(make_scanned_pdf())
    planned = plan_document(normalize_document(parsed), 800, 80)
    assert planned[0].chunks[0].kind == "OCR_TEXT"


# ---- Gemini adapter ---------------------------------------------------------------------------
def gemini(handler, **kwargs) -> GeminiVisionOCRProvider:
    client = httpx.Client(
        base_url="https://generativelanguage.googleapis.com/v1beta/",
        transport=httpx.MockTransport(handler),
    )
    return GeminiVisionOCRProvider(
        "test-key",
        "models/test-model",
        client=client,
        sleep=lambda seconds: None,
        **kwargs,
    )


def test_gemini_request_shape_and_response_parsing() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": "Hello "}, {"text": "page"}]}}
                ]
            },
        )

    text = gemini(handler).extract_text(b"\x89PNG-data", 1)

    assert text == "Hello page"
    request = seen[0]
    assert request.url.path == "/v1beta/models/test-model:generateContent"
    assert request.headers["x-goog-api-key"] == "test-key"
    body = json.loads(request.content)
    parts = body["contents"][0]["parts"]
    assert base64.b64decode(parts[0]["inline_data"]["data"]) == b"\x89PNG-data"
    assert parts[0]["inline_data"]["mime_type"] == "image/png"
    assert parts[1]["text"] == OCR_PROMPT  # the instruction comes after the page image
    assert body["generationConfig"]["temperature"] == 0
    assert "verbatim" in OCR_PROMPT and "Do not summarise" in OCR_PROMPT


def test_gemini_retries_rate_limits_and_honours_retry_after() -> None:
    attempts = []
    waits: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) < 3:
            return httpx.Response(429, headers={"retry-after": "7"})
        return httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}
        )

    client = httpx.Client(
        base_url="https://generativelanguage.googleapis.com/v1beta/",
        transport=httpx.MockTransport(handler),
    )
    provider = GeminiVisionOCRProvider("k", "m", client=client, sleep=waits.append)

    assert provider.extract_text(b"png", 1) == "ok"
    assert len(attempts) == 3 and waits == [7.0, 7.0]


def test_gemini_permanent_errors_are_not_retried_and_raise_a_safe_error() -> None:
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(403, json={"error": "API key leaked"})

    with pytest.raises(OCRUnavailableError) as raised:
        gemini(handler).extract_text(b"png", 4)

    assert len(attempts) == 1
    assert "HTTP 403" in str(raised.value) and "leaked" not in str(raised.value)


# ---- consent gate and cache -------------------------------------------------------------------
def test_external_ocr_is_refused_unless_explicitly_allowed() -> None:
    base = get_settings().model_copy(
        update={"ocr_provider": "gemini", "ocr_model": "m"}
    )

    refused = create_ocr_provider(base.model_copy(update={"ocr_allow_external": False}))
    assert isinstance(refused, RefusingOCRProvider)
    with pytest.raises(OCRUnavailableError, match="OCR_ALLOW_EXTERNAL"):
        refused.extract_text(b"png", 1)

    no_key = create_ocr_provider(
        base.model_copy(
            update={
                "ocr_allow_external": True,
                "ocr_api_key": None,
                "gemini_api_key": None,
            }
        )
    )
    assert isinstance(no_key, RefusingOCRProvider)

    assert create_ocr_provider(base.model_copy(update={"ocr_provider": "none"})) is None
    local = create_ocr_provider(base.model_copy(update={"ocr_provider": "tesseract"}))
    assert isinstance(local, TesseractOCRProvider) and local.external is False


def test_tesseract_reports_a_missing_binary_clearly() -> None:
    provider = TesseractOCRProvider(binary="definitely-not-installed-ocr")
    with pytest.raises(OCRUnavailableError, match="not installed"):
        provider.extract_text(b"png", 1)


@pytest.mark.skipif(
    not TesseractOCRProvider.available(), reason="tesseract binary not installed"
)
def test_tesseract_reads_a_rendered_page() -> (
    None
):  # pragma: no cover - needs the binary
    pdf = fitz.open(stream=make_scanned_pdf("BrakeController"), filetype="pdf")
    png = pdf[0].get_pixmap(dpi=200).tobytes("png")
    assert "Brake" in TesseractOCRProvider().extract_text(png, 1)


class DictCache:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def put(self, key: str, text: str) -> None:
        self.store[key] = text


def test_identical_page_images_hit_the_cache_and_cost_nothing() -> None:
    inner = FakeOCR()
    cached = CachingOCRProvider(inner, DictCache(), model="m")

    first = cached.extract_text(b"\x89PNGsame-image", 1)
    second = cached.extract_text(b"\x89PNGsame-image", 9)
    other = cached.extract_text(b"\x89PNGdifferent", 1)

    assert first == second != "" and other != ""
    assert inner.calls == 2 and cached.cache_hits == 1
