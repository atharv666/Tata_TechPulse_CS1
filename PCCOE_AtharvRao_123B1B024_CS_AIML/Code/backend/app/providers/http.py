"""Bounded retry and timeout behavior shared by HTTP provider adapters."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import httpx

from app.core.config import RetrySettings
from app.providers.contracts import ProviderError, ProviderTimeoutError


class RetryingHttpClient:
    """HTTP wrapper that retries transient errors only; it never changes providers."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        retry: RetrySettings,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._client = client
        self._retry = retry
        self._sleep = sleep

    async def post(
        self, path: str, payload: dict[str, object], headers: dict[str, str]
    ) -> httpx.Response:
        """Issue a bounded retry request and return only a successful response."""
        for attempt in range(1, self._retry.max_attempts + 1):
            try:
                response = await self._client.post(path, json=payload, headers=headers)
                if response.status_code < 500 and response.status_code != 429:
                    response.raise_for_status()
                    return response
            except httpx.TimeoutException as error:
                if attempt == self._retry.max_attempts:
                    raise ProviderTimeoutError("Provider request timed out.") from error
            except httpx.HTTPStatusError as error:
                raise ProviderError(
                    f"Provider returned HTTP {error.response.status_code}."
                ) from error
            except httpx.TransportError as error:
                if attempt == self._retry.max_attempts:
                    raise ProviderError("Provider transport request failed.") from error

            if attempt < self._retry.max_attempts:
                await self._sleep(self._retry.initial_backoff_seconds * (2 ** (attempt - 1)))

        raise ProviderError("Provider retry loop ended unexpectedly.")
