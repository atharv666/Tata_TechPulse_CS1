"""Bounded retry and timeout behavior shared by HTTP provider adapters."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from app.core.config import RetrySettings
from app.providers.contracts import (
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderTransientError,
)


def parse_retry_after(value: str | None, now: datetime | None = None) -> float | None:
    """Interpret a ``Retry-After`` header given either as seconds or as an HTTP date."""
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - (now or datetime.now(UTC))).total_seconds())


class RetryingHttpClient:
    """HTTP wrapper that retries transient errors only; it never changes providers.

    * 429 and 5xx responses, timeouts and transport errors are retried with exponential back-off and
      jitter, honouring ``Retry-After`` when the provider sends it.
    * Other 4xx responses are permanent (bad credentials, bad request) and are raised immediately.
    * When the bounded attempts are exhausted a *transient* error is raised so the job runner can
      reschedule the job later instead of marking it failed.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        retry: RetrySettings,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self._client = client
        self._retry = retry
        self._sleep = sleep
        self._jitter = jitter

    def _delay(self, attempt: int, retry_after: float | None) -> float:
        backoff = self._retry.initial_backoff_seconds * (2 ** (attempt - 1))
        backoff += backoff * 0.25 * self._jitter()
        delay = max(backoff, retry_after or 0.0)
        return float(min(delay, self._retry.max_backoff_seconds))

    async def post(
        self, path: str, payload: dict[str, object], headers: dict[str, str]
    ) -> httpx.Response:
        """Issue a bounded retry request and return only a successful response."""
        last_error: ProviderTransientError | None = None
        for attempt in range(1, self._retry.max_attempts + 1):
            retry_after: float | None = None
            try:
                response = await self._client.post(path, json=payload, headers=headers)
            except httpx.TimeoutException as error:
                last_error = ProviderTimeoutError("Provider request timed out.")
                last_error.__cause__ = error
            except httpx.TransportError as error:
                last_error = ProviderTransientError("Provider transport request failed.")
                last_error.__cause__ = error
            else:
                if response.status_code == 429 or response.status_code >= 500:
                    retry_after = parse_retry_after(response.headers.get("retry-after"))
                    if response.status_code == 429:
                        last_error = ProviderRateLimitError(
                            "Provider rate limit reached (HTTP 429).", retry_after
                        )
                    else:
                        last_error = ProviderTransientError(
                            f"Provider returned HTTP {response.status_code}.", retry_after
                        )
                else:
                    try:
                        response.raise_for_status()
                    except httpx.HTTPStatusError as error:
                        raise ProviderError(
                            f"Provider returned HTTP {error.response.status_code}."
                        ) from error
                    return response
            if last_error is not None and last_error.retry_after_seconds is None:
                last_error.retry_after_seconds = retry_after
            if attempt < self._retry.max_attempts:
                await self._sleep(self._delay(attempt, retry_after))
        assert last_error is not None
        raise last_error
