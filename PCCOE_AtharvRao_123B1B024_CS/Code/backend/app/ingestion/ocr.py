"""OCR providers for scanned pages, behind the ``OCRProvider`` boundary of the PDF parser.

* ``TesseractOCRProvider`` - local binary; page images never leave the machine (the target
  deployment).
* ``GeminiVisionOCRProvider`` - hosted vision model through the Gemini REST API. It is ``external``:
  page images are sent to a third party, so it is refused unless ``OCR_ALLOW_EXTERNAL=true``, and
  every use is recorded in the audit log. Use it only with synthetic / non-confidential documents.
* ``CachingOCRProvider`` - de-duplicates identical page images (retries and re-uploads are
  free).

OCR output is *text recovered by a model*, so chunks built from it are flagged ``OCR_TEXT`` and the
facts extracted from them carry a confidence discount and the OCR source classification.
"""

from __future__ import annotations

import base64
import hashlib
import shutil
import subprocess
import time
from typing import Protocol

import httpx

from app.core.config import Settings
from app.ingestion.contracts import IngestionError
from app.ingestion.parsers import OCRProvider, OCRResult
from app.providers.http import parse_retry_after

OCR_PROMPT_VERSION = "ocr-transcribe-v1"
OCR_PROMPT = (
    "Transcribe all text on this page exactly as written, in reading order. "
    "Render tables as Markdown tables. Preserve identifiers, numbers, units and punctuation "
    "verbatim. Do not summarise, translate, correct or add anything. "
    "Write [ILLEGIBLE] for text you cannot read. Output only the transcription."
)


class OCRUnavailableError(IngestionError):
    """OCR was requested but cannot run (not configured, missing binary, external refused)."""


class OCRCache(Protocol):
    def get(self, key: str) -> str | None: ...
    def put(self, key: str, text: str) -> None: ...


class RefusingOCRProvider(OCRProvider):
    """Stands in for a configured-but-unusable provider so the reason reaches the warnings."""

    def __init__(self, reason: str, name: str = "unavailable") -> None:
        self.name = name
        self._reason = reason

    def extract_text(self, image_bytes: bytes, page_number: int) -> str:
        raise OCRUnavailableError(self._reason)


class TesseractOCRProvider(OCRProvider):
    name = "tesseract"
    external = False

    def __init__(
        self, binary: str = "tesseract", language: str = "eng", timeout_seconds: float = 90.0
    ) -> None:
        self._binary = binary
        self._language = language
        self._timeout = timeout_seconds

    @staticmethod
    def available(binary: str = "tesseract") -> bool:
        return shutil.which(binary) is not None

    def extract_text(self, image_bytes: bytes, page_number: int) -> str:
        if not self.available(self._binary):
            raise OCRUnavailableError("Tesseract is not installed on this host.")
        try:
            completed = subprocess.run(
                [self._binary, "stdin", "stdout", "-l", self._language, "--psm", "6"],
                input=image_bytes,
                capture_output=True,
                timeout=self._timeout,
                check=True,
            )
        except subprocess.TimeoutExpired as error:
            raise OCRUnavailableError("Tesseract timed out.") from error
        except subprocess.CalledProcessError as error:
            raise OCRUnavailableError("Tesseract failed to read the page image.") from error
        return completed.stdout.decode("utf-8", errors="replace")


class GeminiVisionOCRProvider(OCRProvider):
    name = "gemini"
    external = True

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta/",
        timeout_seconds: float = 120.0,
        max_attempts: int = 4,
        client: httpx.Client | None = None,
        sleep: object = time.sleep,
    ) -> None:
        self._model = model.removeprefix("models/")
        self._api_key = api_key
        self._max_attempts = max_attempts
        self._client = client or httpx.Client(
            base_url=base_url.rstrip("/") + "/", timeout=timeout_seconds
        )
        self._sleep = sleep

    def extract_text(self, image_bytes: bytes, page_number: int) -> str:
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "inline_data": {
                                "mime_type": "image/png",
                                "data": base64.b64encode(image_bytes).decode("ascii"),
                            }
                        },
                        {"text": OCR_PROMPT},  # prompt after the page, as the API guidance advises
                    ]
                }
            ],
            "generationConfig": {"temperature": 0},
        }
        headers = {"x-goog-api-key": self._api_key, "Content-Type": "application/json"}
        endpoint = f"models/{self._model}:generateContent"
        last = "unknown error"
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = self._client.post(endpoint, json=payload, headers=headers)
            except httpx.HTTPError as error:
                last = f"transport error ({type(error).__name__})"
            else:
                if response.status_code == 200:
                    return _gemini_text(response.json())
                last = f"HTTP {response.status_code}"
                if response.status_code not in (429, 500, 502, 503, 504):
                    break
                delay = parse_retry_after(response.headers.get("retry-after")) or 2.0 * attempt
                if attempt < self._max_attempts:
                    self._sleep(min(delay, 60.0))  # type: ignore[operator]
                continue
            if attempt < self._max_attempts:
                self._sleep(2.0 * attempt)  # type: ignore[operator]
        raise OCRUnavailableError(f"Gemini OCR failed for page {page_number}: {last}.")


def _gemini_text(body: dict[str, object]) -> str:
    try:
        candidates = body["candidates"]
        parts = candidates[0]["content"]["parts"]  # type: ignore[index]
        return "".join(str(part.get("text", "")) for part in parts)
    except (KeyError, IndexError, TypeError) as error:
        raise OCRUnavailableError("Gemini OCR returned no text.") from error


class CachingOCRProvider(OCRProvider):
    def __init__(self, inner: OCRProvider, cache: OCRCache, model: str = "") -> None:
        self._inner = inner
        self._cache = cache
        self.name = inner.name
        self.external = inner.external
        self._namespace = f"{inner.name}:{model}:{OCR_PROMPT_VERSION}"
        self.cache_hits = 0
        self.provider_calls = 0

    def extract_text(self, image_bytes: bytes, page_number: int) -> str:
        return self.extract(image_bytes, page_number).text

    def extract(self, image_bytes: bytes, page_number: int) -> OCRResult:
        key = f"{self._namespace}:{hashlib.sha256(image_bytes).hexdigest()}"
        cached = self._cache.get(key)
        if cached is not None:
            self.cache_hits += 1
            return OCRResult(cached)
        self.provider_calls += 1
        result = self._inner.extract(image_bytes, page_number)
        self._cache.put(key, result.text)
        return result


def create_ocr_provider(settings: Settings) -> OCRProvider | None:
    """The configured provider, or ``None`` when OCR is off. External use needs explicit consent."""
    choice = settings.ocr_provider
    if choice == "none":
        return None
    if choice == "tesseract":
        return TesseractOCRProvider(settings.ocr_tesseract_binary, settings.ocr_language)
    if choice == "gemini":
        if not settings.ocr_allow_external:
            return RefusingOCRProvider(
                "External OCR (Gemini) is disabled. Set OCR_ALLOW_EXTERNAL=true only for "
                "synthetic or non-confidential documents.",
                name="gemini",
            )
        api_key = settings.ocr_api_key or settings.gemini_api_key
        if api_key is None or not settings.ocr_model:
            return RefusingOCRProvider("Gemini OCR needs OCR_MODEL and an API key.", name="gemini")
        return GeminiVisionOCRProvider(
            api_key.get_secret_value(),
            settings.ocr_model,
            str(settings.ocr_base_url or "https://generativelanguage.googleapis.com/v1beta/"),
        )
    return None
