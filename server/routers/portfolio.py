from __future__ import annotations

import asyncio
import logging
import math
import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request

from server.data import analysis, eastmoney, nasdaq

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])
ET = ZoneInfo("America/New_York")

BENCHMARK_DAYS = {
    "1M": 45,
    "3M": 110,
    "6M": 220,
    "YTD": 300,
    "1Y": 420,
    "3Y": 1150,
    "5Y": 1900,
}

ALLOWED_RANGES = ("1Y", "3Y", "5Y")
ALLOWED_REBALANCE = ("buy_hold", "monthly", "quarterly", "annual")
ALLOWED_BENCHMARKS = ("SPY", "QQQ", "IWM", "DIA")
MAX_HOLDINGS = 20
_SYMBOL_PATTERN = re.compile(r"[A-Z0-9][A-Z0-9.\-]{0,15}")


def _bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=400, detail=message)


def _clean_symbol(value: Any) -> str:
    if not isinstance(value, str):
        raise _bad_request("持仓代码必须是字符串")
    symbol = value.strip().upper()
    if not _SYMBOL_PATTERN.fullmatch(symbol):
        raise _bad_request(f"持仓代码无效：{value}")
    return symbol


def _parse_backtest_request(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise _bad_request("请求体必须是 JSON 对象")
    raw_holdings = payload.get("holdings")
    if not isinstance(raw_holdings, list) or not 1 <= len(raw_holdings) <= MAX_HOLDINGS:
        raise _bad_request(f"holdings 必须包含 1 到 {MAX_HOLDINGS} 个持仓")

    holdings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_holdings:
        if not isinstance(item, dict):
            raise _bad_request("每个持仓必须是对象")
        symbol = _clean_symbol(item.get("symbol"))
        if symbol in seen:
            raise _bad_request(f"持仓代码重复：{symbol}")
        raw_weight = item.get("weight")
        if isinstance(raw_weight, bool) or not isinstance(raw_weight, (int, float)):
            raise _bad_request(f"{symbol} 的目标权重必须是正数")
        try:
            weight = float(raw_weight)
        except (TypeError, ValueError, OverflowError) as exc:
            raise _bad_request(f"{symbol} 的目标权重必须是正数") from exc
        if not math.isfinite(weight) or weight <= 0:
            raise _bad_request(f"{symbol} 的目标权重必须是有限正数")
        seen.add(symbol)
        holdings.append({"symbol": symbol, "weight": weight})

    raw_range = payload.get("range")
    if not isinstance(raw_range, str) or raw_range.strip().upper() not in ALLOWED_RANGES:
        raise _bad_request("range 仅支持 1Y、3Y、5Y")
    range_name = raw_range.strip().upper()

    raw_rebalance = payload.get("rebalance")
    if not isinstance(raw_rebalance, str):
        raise _bad_request("rebalance 仅支持 buy_hold、monthly、quarterly、annual")
    rebalance = raw_rebalance.strip().lower()
    if rebalance not in ALLOWED_REBALANCE:
        raise _bad_request("rebalance 仅支持 buy_hold、monthly、quarterly、annual")

    raw_benchmark = payload.get("benchmark")
    if not isinstance(raw_benchmark, str):
        raise _bad_request("benchmark 仅支持 SPY、QQQ、IWM、DIA")
    benchmark = raw_benchmark.strip().upper()
    if benchmark not in ALLOWED_BENCHMARKS:
        raise _bad_request("benchmark 仅支持 SPY、QQQ、IWM、DIA")

    try:
        normalized = analysis.normalize_portfolio_weights(holdings)
    except ValueError as exc:
        raise _bad_request(str(exc)) from exc

    return {
        "holdings": normalized,
        "range": range_name,
        "rebalance": rebalance,
        "benchmark": benchmark,
    }


@router.post("/backtest")
async def backtest(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception as exc:
        raise _bad_request("请求体必须是合法的 JSON 对象") from exc
    params = _parse_backtest_request(payload)
    holdings = params["holdings"]
    symbols = [item["symbol"] for item in holdings]
    range_name = params["range"]
    rebalance = params["rebalance"]
    benchmark_symbol = params["benchmark"]
    warnings: list[str] = []
    semaphore = asyncio.Semaphore(5)
    raw_symbols: list[str] = []

    async def fetch_universe() -> dict[str, Any]:
        try:
            return await eastmoney.universe(3000)
        except Exception as exc:
            logger.warning("portfolio universe failed: %s", exc)
            warnings.append("全市场快照暂不可用，行业分布可能不完整")
            return {"items": []}

    async def fetch_quotes() -> list[dict[str, Any]]:
        try:
            return await eastmoney.quotes(symbols)
        except Exception as exc:
            logger.info("portfolio quotes failed: %s", exc)
            warnings.append("实时行情暂不可用，名称与行业信息可能不完整")
            return []

    async def fetch_benchmark() -> list[dict[str, Any]]:
        days = BENCHMARK_DAYS[range_name]
        try:
            bars = await nasdaq.historical_etf(benchmark_symbol, days)
            if not bars:
                warnings.append(f"基准 {benchmark_symbol} 历史行情为空，已跳过基准对比。")
            return bars or []
        except Exception as exc:
            logger.info("portfolio benchmark %s failed: %s", benchmark_symbol, exc)
            warnings.append(f"基准 {benchmark_symbol} 历史行情暂不可用，已跳过基准对比。")
            return []

    async def fetch_bars(item: dict[str, Any]) -> dict[str, Any]:
        symbol = item["symbol"]
        async with semaphore:
            try:
                data = await eastmoney.candles(symbol, range_name)
            except Exception as exc:
                logger.info("portfolio candles failed for %s: %s", symbol, exc)
                warnings.append(f"{symbol} 历史行情暂不可用")
                return {"symbol": symbol, "bars": [], "source": None, "price_basis": None}
        if not isinstance(data, dict):
            warnings.append(f"{symbol} 历史行情暂不可用")
            return {"symbol": symbol, "bars": [], "source": None, "price_basis": None}
        bars = data.get("bars") or []
        source = data.get("source")
        price_basis = data.get("price_basis")
        if not bars:
            warnings.append(f"{symbol} 历史行情暂不可用")
        elif source == "nasdaq" or price_basis == "raw":
            raw_symbols.append(symbol)
        elif source != "eastmoney" or price_basis not in (None, "forward_adjusted"):
            raw_symbols.append(symbol)
        return {
            "symbol": symbol,
            "name": data.get("name"),
            "bars": bars,
            "source": source,
            "price_basis": price_basis,
        }

    universe_data, quote_list, benchmark_bars, bars_results = await asyncio.gather(
        fetch_universe(),
        fetch_quotes(),
        fetch_benchmark(),
        asyncio.gather(*(fetch_bars(item) for item in holdings)),
    )

    universe_map = {
        str(item.get("symbol") or "").strip().upper(): item
        for item in (universe_data.get("items") or [])
        if isinstance(item, dict)
    }
    quote_map = {
        str(item.get("symbol") or "").strip().upper(): item
        for item in (quote_list or [])
        if isinstance(item, dict)
    }
    bars_map: dict[str, dict[str, Any]] = {}
    names: dict[str, str] = {}
    sector_map: dict[str, str] = {}
    for result in bars_results:
        symbol = result["symbol"]
        bars_map[symbol] = result
        quote = quote_map.get(symbol) or {}
        universe_item = universe_map.get(symbol) or {}
        name = (
            quote.get("name")
            or result.get("name")
            or universe_item.get("name")
            or symbol
        )
        names[symbol] = str(name)
        sector = universe_item.get("industry") or quote.get("industry")
        if sector:
            sector_map[symbol] = str(sector)

    if raw_symbols:
        warnings.append(
            f"{len(set(raw_symbols))} 只成分使用未复权或非东方财富行情，复权口径差异可能影响收益；来源见成分表。"
        )

    result = analysis.backtest_portfolio(
        [
            {"symbol": item["symbol"], "weight": item["normalized"]}
            for item in holdings
        ],
        bars_map,
        benchmark_bars,
        benchmark_symbol,
        rebalance,
        range_name,
        names,
        sector_map,
    )
    warnings = list(dict.fromkeys(warnings))
    result["warnings"] = list(dict.fromkeys((result.get("warnings") or []) + warnings))
    result["as_of"] = datetime.now(ET).isoformat(timespec="seconds")
    result["range"] = range_name
    result["benchmark"] = benchmark_symbol
    result["rebalance"] = rebalance
    benchmark_used = bool(result.get("performance", {}).get("benchmark"))
    result["benchmark_source"] = "nasdaq" if benchmark_used else None
    result["benchmark_price_basis"] = "raw" if benchmark_used else None
    result["ex_fees"] = True
    return result
