from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query

from server.data import analysis, eastmoney, nasdaq

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["compare"])
ET = ZoneInfo("America/New_York")

BENCHMARK_DAYS = {
    "1M": 45,
    "3M": 110,
    "6M": 220,
    "YTD": 300,
    "1Y": 420,
    "3Y": 1150,
    "5Y": 1900,
    "MAX": 3000,
}
INTRADAY = {"1D", "5D"}


@router.get("/compare")
async def compare(symbols: str = Query(..., min_length=1), range: str = Query("1Y")) -> dict[str, Any]:
    range = (range or "1Y").upper()
    tickers = list(dict.fromkeys(item.strip().upper() for item in symbols.split(",") if item.strip()))[:6]
    if not tickers:
        return {"symbols": [], "performance": {"dates": [], "series": {}}, "metrics": [], "correlation": []}
    errors: list[str] = []
    semaphore = asyncio.Semaphore(4)

    async def fetch(symbol: str) -> dict[str, Any] | None:
        async with semaphore:
            try:
                payload = await eastmoney.candles(symbol, range)
                return {
                    "symbol": payload["symbol"],
                    "name": payload["name"],
                    "bars": payload.get("bars") or [],
                    "source": payload.get("source"),
                    "degraded": bool(payload.get("degraded")),
                }
            except Exception as exc:
                logger.info("compare candles failed for %s: %s", symbol, exc)
                errors.append(f"{symbol} 行情获取失败")
                return None

    async def fetch_benchmark() -> list[dict[str, Any]] | None:
        if range in INTRADAY:
            return None
        try:
            return await nasdaq.historical_etf("SPY", BENCHMARK_DAYS.get(range, 420))
        except Exception as exc:
            logger.info("benchmark fetch failed: %s", exc)
            errors.append("SPY 基准获取失败")
            return None

    benchmark_task = asyncio.create_task(fetch_benchmark())
    entries = [entry for entry in await asyncio.gather(*(fetch(item) for item in tickers)) if entry]
    benchmark_bars = await benchmark_task
    result = analysis.compare(entries, benchmark_bars)
    result["sources"] = {entry["symbol"]: entry.get("source") for entry in entries}
    quote_items = await eastmoney.quotes([entry["symbol"] for entry in entries])
    result["quotes"] = {
        item["symbol"]: {
            "price": item.get("price"),
            "change_pct": item.get("change_pct"),
            "market_cap": item.get("market_cap"),
            "pe": item.get("pe"),
        }
        for item in quote_items
    }
    result["range"] = range
    result["errors"] = errors
    result["as_of"] = datetime.now(ET).isoformat(timespec="seconds")
    return result
