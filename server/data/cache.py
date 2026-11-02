from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, TypeVar

logger = logging.getLogger(__name__)
T = TypeVar("T")


def _safe_name(key: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "_", key).strip("_")[:72] or "cache"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
    return f"{slug}_{digest}.json"


class JsonCache:
    """In-process TTL cache with JSON disk persistence and stale-on-error."""

    def __init__(self, directory: Path, enabled: bool | None = None) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.enabled = (
            os.getenv("US_CACHE_DISABLE", "").lower() not in {"1", "true", "yes"}
            if enabled is None
            else enabled
        )
        self._memory: dict[str, tuple[float, Any]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._files: dict[str, Path] = {}
        self._refreshing: set[str] = set()
        self._tasks: set[asyncio.Task] = set()

    def _path(self, key: str) -> Path:
        path = self._files.get(key)
        if path is None:
            path = self.directory / _safe_name(key)
            self._files[key] = path
        return path

    def peek(self, key: str) -> tuple[bool, Any]:
        entry = self._memory.get(key)
        if entry and entry[0] > time.time():
            return True, entry[1]
        return False, None

    def read_stale(self, key: str) -> Any:
        """Read the last persisted value regardless of TTL; used by degraded modes."""
        if not self.enabled:
            return None
        _, value = self._read_disk(key)
        return value

    async def get(
        self,
        key: str,
        ttl: float,
        factory: Callable[[], Awaitable[T]],
        *,
        persist: bool = True,
        allow_stale: bool = True,
    ) -> T:
        if not self.enabled:
            return await factory()

        now = time.time()
        entry = self._memory.get(key)
        if entry and entry[0] > now:
            return entry[1]

        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            now = time.time()
            entry = self._memory.get(key)
            if entry and entry[0] > now:
                return entry[1]

            saved_at: float | None = None
            stale: Any = None
            if persist:
                saved_at, stale = await asyncio.to_thread(self._read_disk, key)
                if saved_at is not None and saved_at + ttl > now and stale is not None:
                    self._memory[key] = (saved_at + ttl, stale)
                    return stale

            try:
                value = await factory()
            except Exception:
                if allow_stale and stale is not None:
                    logger.warning("upstream failed for %s; serving stale cache", key, exc_info=True)
                    return stale
                raise

            self._memory[key] = (time.time() + ttl, value)
            if persist:
                await asyncio.to_thread(self._write_disk, key, value)
            return value

    async def get_swr(
        self,
        key: str,
        ttl: float,
        factory: Callable[[], Awaitable[T]],
        *,
        persist: bool = True,
        max_stale: float = 6 * 3600,
    ) -> T:
        """Serve cached data immediately and refresh in the background when expired."""
        if not self.enabled:
            return await factory()

        now = time.time()
        entry = self._memory.get(key)
        if entry:
            expires, value = entry
            if expires > now:
                return value
            if now - expires <= max_stale:
                self._schedule_refresh(key, ttl, factory, persist)
                return value

        saved_at: float | None = None
        stale: Any = None
        if persist:
            saved_at, stale = await asyncio.to_thread(self._read_disk, key)
        if stale is not None and saved_at is not None and now - saved_at <= max_stale:
            self._memory[key] = (saved_at + ttl, stale)
            self._schedule_refresh(key, ttl, factory, persist)
            return stale

        return await self.get(key, ttl, factory, persist=persist, allow_stale=True)

    def _schedule_refresh(
        self,
        key: str,
        ttl: float,
        factory: Callable[[], Awaitable[T]],
        persist: bool,
    ) -> None:
        if key in self._refreshing:
            return
        self._refreshing.add(key)
        task = asyncio.create_task(self._refresh(key, ttl, factory, persist))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _refresh(
        self,
        key: str,
        ttl: float,
        factory: Callable[[], Awaitable[T]],
        persist: bool,
    ) -> None:
        try:
            value = await factory()
            self._memory[key] = (time.time() + ttl, value)
            if persist:
                await asyncio.to_thread(self._write_disk, key, value)
        except Exception:
            logger.warning("background refresh failed for %s; keeping stale cache", key, exc_info=True)
        finally:
            self._refreshing.discard(key)

    def _read_disk(self, key: str) -> tuple[float | None, Any]:
        path = self._path(key)
        try:
            with path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
            return float(payload.get("t", 0)), payload.get("v")
        except (OSError, ValueError, TypeError):
            return None, None

    def _write_disk(self, key: str, value: Any) -> None:
        path = self._path(key)
        tmp = path.with_suffix(".tmp")
        payload = {"t": time.time(), "v": value}
        try:
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
            os.replace(tmp, path)
        except (OSError, TypeError, ValueError):
            logger.warning("failed to persist cache entry %s", key, exc_info=True)
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

    def invalidate(self, key: str) -> None:
        self._memory.pop(key, None)
        try:
            self._path(key).unlink(missing_ok=True)
        except OSError:
            pass

    def clear(self) -> None:
        self._memory.clear()
        for path in self.directory.glob("*.json"):
            try:
                path.unlink()
            except OSError:
                pass
