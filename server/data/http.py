from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

from server.config import BROWSER_UA, HTTP_RETRIES, HTTP_TIMEOUT

logger = logging.getLogger(__name__)


class UpstreamError(RuntimeError):
    pass


def _parse_jsonp(text: str) -> Any:
    start = text.find("(")
    end = text.rfind(")")
    if start == -1 or end <= start:
        raise UpstreamError("invalid JSONP response")
    return json.loads(text[start + 1 : end])


class HttpClient:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()

    async def client(self) -> httpx.AsyncClient:
        if self._client is None:
            async with self._lock:
                if self._client is None:
                    self._client = httpx.AsyncClient(
                        timeout=httpx.Timeout(HTTP_TIMEOUT, connect=10.0),
                        follow_redirects=True,
                        limits=httpx.Limits(
                            max_connections=32, max_keepalive_connections=16
                        ),
                        headers={"User-Agent": BROWSER_UA},
                    )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def get_text(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        retries: int = HTTP_RETRIES,
        timeout: float | None = None,
    ) -> str:
        content = await self.get_bytes(
            url, params=params, headers=headers, retries=retries, timeout=timeout
        )
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            # Eastmoney's push2 JSON is GBK-encoded despite the missing charset header.
            return content.decode("gb18030", errors="replace")

    async def get_bytes(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        retries: int = HTTP_RETRIES,
        timeout: float | None = None,
    ) -> bytes:
        client = await self.client()
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                response = await client.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=timeout or HTTP_TIMEOUT,
                )
                if response.status_code >= 400:
                    if response.status_code < 500 and response.status_code != 429:
                        raise UpstreamError(
                            f"upstream returned HTTP {response.status_code}"
                        )
                    raise httpx.HTTPStatusError(
                        f"HTTP {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                return response.content
            except (httpx.HTTPError, UpstreamError) as exc:
                last_error = exc
                if attempt >= retries:
                    break
                await asyncio.sleep(0.35 * (attempt + 1))
        raise UpstreamError(
            f"request failed: {url} ({type(last_error).__name__}: {last_error})"
        )

    async def get_prefix(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        limit: int = 16384,
        timeout: float | None = None,
    ) -> bytes:
        """Read only the first `limit` bytes; upstreams like EDGAR ignore Range on large files."""
        client = await self.client()
        async with client.stream(
            "GET", url, params=params, headers=headers, timeout=timeout or HTTP_TIMEOUT
        ) as response:
            if response.status_code >= 400:
                raise UpstreamError(f"upstream returned HTTP {response.status_code}")
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                chunks.append(chunk)
                size += len(chunk)
                if size >= limit:
                    break
        return b"".join(chunks)[:limit]

    async def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        jsonp: bool = False,
        retries: int = HTTP_RETRIES,
        timeout: float | None = None,
        optional: bool = False,
    ) -> Any:
        try:
            text = await self.get_text(
                url,
                params=params,
                headers=headers,
                retries=retries,
                timeout=timeout,
            )
        except UpstreamError:
            if optional:
                return None
            raise
        try:
            return _parse_jsonp(text) if jsonp else json.loads(text)
        except (json.JSONDecodeError, ValueError) as exc:
            if optional:
                return None
            raise UpstreamError(f"invalid JSON from {url}") from exc


http = HttpClient()
