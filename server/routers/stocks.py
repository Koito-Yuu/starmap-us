from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from fastapi.params import Query as QueryParam

from server.data import analysis, eastmoney, edgar, nasdaq, sec

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/stocks", tags=["stocks"])
ET = ZoneInfo("America/New_York")


class _InvalidIndicatorParams(HTTPException, ValueError):
    """Invalid chart params: a 400 response and a ValueError for direct callers."""

    def __init__(self, detail: str):
        HTTPException.__init__(self, status_code=400, detail=detail)
        ValueError.__init__(self, detail)


def _parse_chart_params(raw: str | None) -> dict[str, Any] | None:
    if isinstance(raw, QueryParam):  # Direct calls see the FastAPI default object.
        raw = raw.default
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise _InvalidIndicatorParams("params 必须是合法的 JSON 对象") from exc
    if not isinstance(parsed, dict):
        raise _InvalidIndicatorParams("params 必须是合法的 JSON 对象")
    return parsed


async def _optional(
    coro,
    default: Any,
    label: str,
    warnings: list[str],
    timeout: float = 8.0,
) -> Any:
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("%s timed out after %.1fs", label, timeout)
        warnings.append(f"{label} 响应超时")
        return default
    except Exception as exc:
        logger.warning("%s failed: %s", label, exc)
        warnings.append(f"{label} 暂不可用")
        return default


def _merge_snapshot(quote: dict[str, Any], snapshot: dict[str, Any] | None) -> None:
    if not snapshot:
        return
    for field in (
        "pe",
        "pb",
        "industry",
        "float_cap",
        "dividend_yield",
        "chg_60d",
        "chg_ytd",
        "market_cap",
    ):
        if quote.get(field) is None and snapshot.get(field) is not None:
            quote[field] = snapshot[field]


def _peer_rows(universe_items: list[dict[str, Any]], industry: str, symbol: str) -> list[dict[str, Any]]:
    peers = analysis.pick_peers(universe_items, industry, symbol, limit=10)
    return [
        {
            "symbol": item["symbol"],
            "name": item["name"],
            "price": item.get("price"),
            "change_pct": item.get("change_pct"),
            "pe": item.get("pe"),
            "pb": item.get("pb"),
            "market_cap": item.get("market_cap"),
            "chg_ytd": item.get("chg_ytd"),
        }
        for item in peers
    ]


def _prepare_chart_payload(payload: dict[str, Any],
                           params: dict[str, Any] | None = None) -> dict[str, Any]:
    result = dict(payload)
    warmup_bars = result.pop("warmup_bars", None) or []
    bars = result.get("bars") or []
    history = warmup_bars + bars
    warmup_count = len(warmup_bars)

    def trim(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: trim(item) for key, item in value.items()}
        if isinstance(value, list) and len(value) == len(history):
            return value[warmup_count:]
        return value

    result["indicators"] = trim(analysis.indicator_series(history, params))
    result["indicator_params"] = analysis.normalize_indicator_params(params)
    result["warmup_count"] = warmup_count
    return result


@router.get("/{symbol}/overview")
async def overview(symbol: str, params: str | None = Query(None)) -> dict[str, Any]:
    indicator_params = _parse_chart_params(params)
    symbol = symbol.strip().upper()[:16]
    info, quote = await asyncio.gather(
        asyncio.wait_for(eastmoney.resolve(symbol), timeout=7),
        asyncio.wait_for(eastmoney.quote(symbol), timeout=7),
    )
    warnings: list[str] = []
    profile, financials, chart, analyst, dividend, surprises, filings, news, universe_data = await asyncio.gather(
        _optional(eastmoney.profile(symbol), None, "公司资料", warnings, timeout=7),
        _optional(eastmoney.financials(symbol), {"annual": [], "quarterly": []}, "财务数据", warnings, timeout=7),
        _optional(
            eastmoney.candles(symbol, "1Y", warmup=320),
            {"range": "1Y", "intraday": False, "bars": [], "source": None, "degraded": False, "note": None},
            "历史行情",
            warnings,
            timeout=10,
        ),
        _optional(nasdaq.analyst(symbol), None, "分析师评级", warnings, timeout=7),
        _optional(nasdaq.dividends(symbol), None, "股息数据", warnings, timeout=7),
        _optional(nasdaq.earnings_surprise(symbol), [], "盈利惊喜", warnings, timeout=7),
        _optional(sec.filings(symbol, limit=12), {"items": []}, "SEC 申报", warnings, timeout=8),
        _optional(eastmoney.stock_news(symbol, limit=10), [], "个股新闻", warnings, timeout=6),
        _optional(eastmoney.universe(3000), {"items": []}, "全市场快照", warnings, timeout=10),
    )
    universe_items = universe_data.get("items") or []
    snapshot = next((item for item in universe_items if item["symbol"] == quote["symbol"]), None)
    _merge_snapshot(quote, snapshot)
    if not quote.get("industry") and profile:
        quote["industry"] = profile.get("industry") or ""
    bars = (chart or {}).get("bars") or []
    score = analysis.score_stock(quote, financials, bars, universe_items, dividend=dividend)
    peers = _peer_rows(universe_items, quote.get("industry") or "", quote["symbol"])
    return {
        "symbol": quote["symbol"],
        "name": quote.get("name"),
        "quote": quote,
        "profile": profile,
        "financials": financials,
        "analyst": analyst,
        "dividends": dividend,
        "earnings_surprise": surprises,
        "score": score,
        "peers": peers,
        "news": news,
        "filings": filings,
        "chart": _prepare_chart_payload(chart or {}, indicator_params),
        "indicator_params": analysis.normalize_indicator_params(indicator_params),
        "chart_meta": {
            "range": (chart or {}).get("range"),
            "bars": len(bars),
            "intraday": (chart or {}).get("intraday"),
        },
        "warnings": warnings,
        "as_of": datetime.now(ET).isoformat(timespec="seconds"),
        "sources": ["eastmoney", "sec_edgar", "nasdaq"],
    }


@router.get("/{symbol}/chart")
async def chart(symbol: str, range: str = Query("1Y"),
                params: str | None = Query(None)) -> dict[str, Any]:
    indicator_params = _parse_chart_params(params)
    payload = await asyncio.wait_for(
        eastmoney.candles(symbol, range, warmup=320), timeout=12
    )
    return _prepare_chart_payload(payload, indicator_params)


@router.get("/{symbol}/financials")
async def financials(symbol: str) -> dict[str, Any]:
    return await eastmoney.financials(symbol)


@router.get("/{symbol}/cashflow")
async def cashflow(symbol: str) -> dict[str, Any]:
    return await edgar.cashflow(symbol)


@router.get("/{symbol}/statements")
async def statements(symbol: str) -> dict[str, Any]:
    symbol = symbol.strip().upper()[:16]
    quote, profile = await asyncio.gather(
        _optional(eastmoney.quote(symbol), {}, "实时报价", []),
        _optional(eastmoney.profile(symbol), None, "公司资料", []),
    )
    return await edgar.statements(
        symbol,
        industry=(quote or {}).get("industry") or (profile or {}).get("industry") or "",
    )


@router.get("/{symbol}/mda")
async def mda(symbol: str) -> dict[str, Any]:
    return await edgar.mda(symbol)


@router.get("/{symbol}/filings")
async def filings(symbol: str, limit: int = Query(15, ge=1, le=40)) -> dict[str, Any]:
    return await sec.filings(symbol, limit=limit)


@router.get("/{symbol}/news")
async def news(symbol: str, limit: int = Query(12, ge=1, le=30)) -> dict[str, Any]:
    return {"symbol": symbol.upper(), "items": await eastmoney.stock_news(symbol, limit=limit), "source": "eastmoney"}


@router.get("/{symbol}/quote")
async def quote(symbol: str) -> dict[str, Any]:
    return await eastmoney.quote(symbol)
