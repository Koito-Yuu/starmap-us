from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Coroutine, TypeVar
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query

from server.config import MACRO_SERIES
from server.data import eastmoney, fred, nasdaq

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["market"])
ET = ZoneInfo("America/New_York")
T = TypeVar("T")


async def safe(
    coro: Coroutine[Any, Any, T],
    default: T,
    label: str,
    warnings: list[str],
    timeout: float = 8.0,
) -> T:
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("%s timed out after %.1fs", label, timeout)
        warnings.append(f"{label} 响应超时")
        return default
    except Exception as exc:
        logger.warning("%s failed: %s", label, exc)
        warnings.append(f"{label} 数据暂不可用")
        return default


_OVERVIEW_CACHE: dict[int, tuple[float, dict[str, Any]]] = {}
_OVERVIEW_TTL = 30.0
_OVERVIEW_REFRESHING: set[int] = set()
_OVERVIEW_TASKS: set[asyncio.Task] = set()
_OVERVIEW_LOCK = asyncio.Lock()


async def _build_overview(universe_limit: int) -> dict[str, Any]:
    warnings: list[str] = []
    indices, sparklines, sectors, universe_data, movers, news, earnings, macro = await asyncio.gather(
        safe(eastmoney.indices(), [], "指数行情", warnings, timeout=6),
        safe(eastmoney.index_trends(), {}, "指数走势", warnings, timeout=9),
        safe(eastmoney.sector_performance(), [], "板块表现", warnings, timeout=7),
        safe(eastmoney.universe(universe_limit), {"items": []}, "全市场快照", warnings, timeout=10),
        safe(eastmoney.movers(), {"gainers": [], "losers": [], "active": []}, "异动榜", warnings, timeout=7),
        safe(eastmoney.fast_news(20), [], "市场快讯", warnings, timeout=5),
        safe(nasdaq.earnings_calendar(7), [], "财报日历", warnings, timeout=6),
        safe(_macro_cards(warnings), [], "宏观快照", warnings, timeout=8),
    )
    items = universe_data.get("items") or []
    heatmap = [
        {
            "symbol": item["symbol"],
            "name": item["name"],
            "change_pct": item.get("change_pct"),
            "market_cap": item.get("market_cap"),
            "industry": item.get("industry"),
        }
        for item in items
        if not item.get("is_etf") and item.get("market_cap") and item.get("change_pct") is not None
    ][:180]
    return {
        "as_of": datetime.now(ET).isoformat(timespec="seconds"),
        "status": eastmoney.market_status(),
        "indices": indices,
        "sparklines": sparklines,
        "sectors": sectors,
        "breadth": _breadth(items),
        "heatmap": heatmap,
        "movers": movers,
        "news": news,
        "earnings": earnings,
        "macro": macro,
        "universe": {
            "sample": len(items),
            "total": universe_data.get("total_market"),
            "source": universe_data.get("source"),
            "updated_at": universe_data.get("updated_at"),
        },
        "warnings": warnings,
    }


def _store_overview(limit: int, payload: dict[str, Any]) -> None:
    _OVERVIEW_CACHE[limit] = (time.monotonic() + _OVERVIEW_TTL, payload)


def _schedule_overview_refresh(limit: int) -> None:
    if limit in _OVERVIEW_REFRESHING:
        return
    _OVERVIEW_REFRESHING.add(limit)

    async def refresh() -> None:
        try:
            async with _OVERVIEW_LOCK:
                cached = _OVERVIEW_CACHE.get(limit)
                if cached and cached[0] > time.monotonic():
                    return
                _store_overview(limit, await _build_overview(limit))
        except Exception:
            logger.warning("overview background refresh failed", exc_info=True)
        finally:
            _OVERVIEW_REFRESHING.discard(limit)

    task = asyncio.create_task(refresh())
    _OVERVIEW_TASKS.add(task)
    task.add_done_callback(_OVERVIEW_TASKS.discard)


@router.get("/market/overview")
async def overview(universe_limit: int = Query(3000, ge=300, le=4000)) -> dict[str, Any]:
    now = time.monotonic()
    cached = _OVERVIEW_CACHE.get(universe_limit)
    if cached:
        expires, payload = cached
        if expires > now:
            return payload
        if now - expires <= 300:
            _schedule_overview_refresh(universe_limit)
            return payload
    async with _OVERVIEW_LOCK:
        cached = _OVERVIEW_CACHE.get(universe_limit)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        payload = await _build_overview(universe_limit)
        _store_overview(universe_limit, payload)
        return payload


def _breadth(items: list[dict[str, Any]]) -> dict[str, Any]:
    changes = [
        float(item["change_pct"])
        for item in items
        if not item.get("is_etf") and item.get("change_pct") is not None
    ]
    if not changes:
        return {
            "sample": 0,
            "advancers": 0,
            "decliners": 0,
            "unchanged": 0,
            "up_ratio": None,
            "median_change": None,
            "avg_change": None,
        }
    advancers = sum(1 for value in changes if value > 0.05)
    decliners = sum(1 for value in changes if value < -0.05)
    unchanged = len(changes) - advancers - decliners
    ordered = sorted(changes)
    middle = len(ordered) // 2
    median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
    return {
        "sample": len(changes),
        "advancers": advancers,
        "decliners": decliners,
        "unchanged": unchanged,
        "up_ratio": round(advancers / len(changes) * 100, 1),
        "median_change": round(median, 2),
        "avg_change": round(sum(changes) / len(changes), 2),
    }


async def _macro_cards(warnings: list[str]) -> list[dict[str, Any]]:
    async def card(series_id: str, label: str | None = None, decimals: int = 2) -> dict[str, Any] | None:
        try:
            points = await fred.series_raw(series_id, years=1)
        except Exception:
            return None
        if not points:
            return None
        meta = MACRO_SERIES[series_id]
        latest = points[-1]
        previous = points[-2] if len(points) > 1 else None
        return {
            "id": series_id,
            "label": label or meta["label"],
            "value": latest["v"],
            "unit": meta["unit"],
            "decimals": decimals,
            "delta": round(latest["v"] - previous["v"], 4) if previous else None,
            "delta_label": "较前值",
            "as_of": latest["d"],
        }

    results = await asyncio.gather(
        card("VIXCLS", "VIX 恐慌指数"),
        card("DGS10", "10 年期美债收益率", 3),
        card("T10Y2Y", "10Y-2Y 利差"),
        card("FEDFUNDS", "联邦基金利率"),
    )
    cards = [item for item in results if item]
    if len(cards) < 4:
        warnings.append("部分宏观序列暂不可用")
    return cards


@router.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "starmap-us-terminal",
        "time": datetime.now(ET).isoformat(timespec="seconds"),
    }


@router.get("/market/status")
async def status() -> dict[str, Any]:
    return eastmoney.market_status()


@router.get("/market/earnings")
async def earnings(days: int = Query(7, ge=1, le=14)) -> dict[str, Any]:
    return {"items": await nasdaq.earnings_calendar(days), "source": "nasdaq"}


@router.get("/search")
async def search(q: str = Query(..., min_length=1, max_length=48), limit: int = Query(10, ge=1, le=20)) -> dict[str, Any]:
    results = await eastmoney.search_us(q, limit=limit)
    return {"query": q, "items": results}


@router.get("/quotes")
async def quotes(symbols: str = Query(..., min_length=1)) -> dict[str, Any]:
    requested = [item.strip().upper() for item in symbols.split(",") if item.strip()]
    requested = list(dict.fromkeys(requested))[:24]
    if not requested:
        return {"items": [], "errors": []}
    warnings: list[str] = []
    universe_data = await safe(eastmoney.universe(3000), {"items": []}, "全市场快照", warnings)
    lookup = {item["symbol"]: item for item in universe_data.get("items") or []}
    results = await eastmoney.quotes(requested)
    items = []
    for item in results:
        snapshot = lookup.get(item["symbol"])
        if snapshot:
            for field in ("pe", "pb", "industry", "market_cap", "float_cap", "dividend_yield", "chg_ytd", "chg_60d"):
                if item.get(field) is None and snapshot.get(field) is not None:
                    item[field] = snapshot[field]
            item["industry"] = item.get("industry") or snapshot.get("industry")
        items.append(item)
    found = {item["symbol"] for item in items}
    return {
        "items": items,
        "errors": [
            {"symbol": symbol, "message": "未找到行情"} for symbol in requested if symbol not in found
        ],
    }
