from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from server.config import CACHE_DIR, NASDAQ_HEADERS
from server.data.cache import JsonCache
from server.data.http import UpstreamError, http

logger = logging.getLogger(__name__)
cache = JsonCache(CACHE_DIR)
ET = ZoneInfo("America/New_York")
BASE = "https://api.nasdaq.com/api"
SPECIAL_SECURITY_RE = re.compile(
    r"\b(?:warrants?|units|rights?|preferred|preference|notes?|debentures?|bonds?)\b",
    re.I,
)


def _num(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).replace("$", "").replace(",", "").replace("%", "").strip()
    if not text or text in {"--", "N/A", "-"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


async def _data(path: str, params: dict[str, Any] | None = None) -> Any:
    payload = await http.get_json(
        f"{BASE}/{path}",
        params=params,
        headers=NASDAQ_HEADERS,
        optional=True,
    )
    return (payload or {}).get("data") if isinstance(payload, dict) else None


async def quote_info(symbol: str) -> dict[str, Any] | None:
    data = await _data(f"quote/{symbol.upper()}/info", {"assetclass": "stocks"})
    if not isinstance(data, dict):
        return None
    return {
        "symbol": data.get("symbol"),
        "company_name": data.get("companyName"),
        "exchange": data.get("exchange"),
        "stock_type": data.get("stockType"),
    }


async def _historical(symbol: str, days: int, assetclass: str) -> list[dict[str, Any]]:
    key = f"nasdaq-hist:v4:{assetclass}:{symbol.upper()}:{days}"

    async def factory() -> list[dict[str, Any]]:
        base = datetime.now(ET) - timedelta(days=max(days, 30) + 30)
        rows: list[dict[str, Any]] = []
        for offset in (0, 10, 30, 60):
            start = (base + timedelta(days=offset)).strftime("%Y-%m-%d")
            data = await _data(
                f"quote/{symbol.upper()}/historical",
                {"assetclass": assetclass, "fromdate": start, "limit": 5000},
            )
            rows = (
                (((data or {}).get("tradesTable") or {}).get("rows") or [])
                if isinstance(data, dict)
                else []
            )
            if rows:
                break
            await asyncio.sleep(0.4)
        bars = []
        for row in rows:
            try:
                date_value = datetime.strptime(row.get("date") or "", "%m/%d/%Y").strftime("%Y-%m-%d")
            except ValueError:
                continue
            close = _num(row.get("close"))
            if close is None:
                continue
            bar: dict[str, Any] = {
                "t": date_value,
                "o": _num(row.get("open")),
                "h": _num(row.get("high")),
                "l": _num(row.get("low")),
                "c": close,
                "v": _num(row.get("volume")),
            }
            adjusted = _num(row.get("adjustedClose"))
            if adjusted is not None:
                bar["a"] = adjusted
            bars.append(bar)
        bars.sort(key=lambda item: item["t"])
        return bars[-days:]

    return await cache.get(key, 1800, factory)


async def historical_etf(symbol: str, days: int = 500) -> list[dict[str, Any]]:
    return await _historical(symbol, days, "etf")


async def historical(symbol: str, days: int = 500) -> list[dict[str, Any]]:
    bars = await _historical(symbol, days, "stocks")
    if not bars:
        bars = await _historical(symbol, days, "etf")
    return bars


FUND_CLASSES = ("mutualfunds", "etf")


async def fund_meta(symbol: str) -> dict[str, Any]:
    """基金/ETF 档案，区分共同基金净值与 ETF 市价。"""

    query = symbol.strip().upper()
    key = f"nasdaq-fundmeta:v2:{query}"

    async def factory() -> dict[str, Any]:
        for assetclass in FUND_CLASSES:
            info = await _data(f"quote/{query}/info", {"assetclass": assetclass})
            if not isinstance(info, dict) or not info.get("companyName"):
                continue
            summary = (await _data(f"quote/{query}/summary", {"assetclass": assetclass}) or {}).get("summaryData") or {}

            def field(name: str) -> str:
                item = summary.get(name)
                if isinstance(item, dict):
                    return str(item.get("value") or "").strip()
                return str(item or "").strip()

            primary = info.get("primaryData") or {}
            return {
                "symbol": query,
                "asset_class": assetclass,
                "name": str(info.get("companyName") or "").strip(),
                "exchange": info.get("exchange"),
                "price": _num(primary.get("lastSalePrice")),
                "price_date": primary.get("lastTradeTimestamp"),
                "price_kind": "market_price" if assetclass == "etf" else "nav",
                "expense_ratio": _num(field("ExpenseRatio")),
                "aum": field("AUM"),
                "beta": _num(field("Beta")),
                "std_dev": _num(field("StandardDeviation")),
                "alpha": _num(field("WeightedAlpha")),
                "week_52": field("FiftTwoWeekHighLow"),
            }
        raise UpstreamError(f"nasdaq 无 {query} 的基金档案")

    return await cache.get(key, 12 * 3600, factory)


async def fund_history(symbol: str, days: int = 1300) -> list[dict[str, Any]]:
    """保留原始收盘值 c 与来源提供的复权值 a，避免混用净值和收益口径。"""

    meta = await fund_meta(symbol)
    return await _historical(symbol, days, meta["asset_class"])


async def etf_holdings(symbol: str) -> list[dict[str, Any]]:
    query = symbol.strip().upper()
    key = f"nasdaq-etf-holdings:v1:{query}"

    async def factory() -> list[dict[str, Any]]:
        data = await _data(f"company/{query}/holdings", {"assetclass": "etf"})
        rows = (((data or {}).get("holdings") or {}).get("rows") or []) if isinstance(data, dict) else []
        return [
            {
                "symbol": str(row.get("symbol") or "").upper(),
                "name": row.get("companyname"),
                "weight": _num(row.get("weighting")),
            }
            for row in rows
            if isinstance(row, dict)
        ]

    return await cache.get(key, 24 * 3600, factory)


async def screener_universe(limit: int = 4000) -> list[dict[str, Any]]:
    key = "nasdaq-screener-universe:v2"

    async def factory() -> list[dict[str, Any]]:
        data = await _data(
            "screener/stocks",
            {"tableonly": "true", "limit": 25, "offset": 0, "download": "true"},
        )
        rows = (data or {}).get("rows") if isinstance(data, dict) else None
        items = []
        for row in rows or []:
            raw_symbol = str(row.get("symbol") or "").strip().upper()
            price = _num(row.get("lastsale"))
            if not raw_symbol or "^" in raw_symbol or price is None or price <= 0:
                continue
            name = str(row.get("name") or raw_symbol).strip()
            if SPECIAL_SECURITY_RE.search(name):
                continue
            symbol = raw_symbol.replace("/", ".")
            upper = name.upper()
            items.append(
                {
                    "symbol": symbol,
                    "em_symbol": symbol.replace(".", "_"),
                    "name": name,
                    "market": 0,
                    "exchange": "US",
                    "price": price,
                    "change": _num(row.get("netchange")),
                    "change_pct": _num(row.get("pctchange")),
                    "volume": _num(row.get("volume")),
                    "amount": None,
                    "pe": None,
                    "pb": None,
                    "market_cap": _num(row.get("marketCap")),
                    "float_cap": None,
                    "chg_60d": None,
                    "chg_ytd": None,
                    "industry": str(row.get("industry") or row.get("sector") or "其他"),
                    "dividend_yield": None,
                    "is_etf": any(token in upper for token in ("ETF", "ETP", "FUND")),
                }
            )
        items.sort(key=lambda item: item.get("market_cap") or 0, reverse=True)
        return items

    items = await cache.get(key, 30 * 60, factory)
    return items[:limit]


async def analyst(symbol: str) -> dict[str, Any] | None:
    key = f"nasdaq-analyst:{symbol.upper()}"

    async def factory() -> dict[str, Any] | None:
        data = await _data(f"analyst/{symbol.upper()}/ratings")
        if not isinstance(data, dict):
            return None
        changes = []
        for item in data.get("upgradesDowngrades") or []:
            if not isinstance(item, dict):
                continue
            changes.append(
                {
                    "date": item.get("date") or item.get("upgradeDowngradeDate") or item.get("lastUpdated"),
                    "firm": item.get("firm") or item.get("brokerName") or item.get("researchFirm"),
                    "action": item.get("action") or item.get("upgradeDowngrade"),
                    "from": item.get("fromGrade") or item.get("previousGrade"),
                    "to": item.get("toGrade") or item.get("currentGrade"),
                }
            )
        return {
            "mean_rating": data.get("meanRatingType"),
            "summary": data.get("ratingsSummary"),
            "analyst_count": len(data.get("brokerNames") or []),
            "changes": changes[:6],
            "source": "nasdaq",
        }

    return await cache.get(key, 24 * 3600, factory)


async def dividends(symbol: str) -> dict[str, Any] | None:
    key = f"nasdaq-dividends:{symbol.upper()}"

    async def factory() -> dict[str, Any] | None:
        data = await _data(f"quote/{symbol.upper()}/dividends", {"assetclass": "stocks"})
        if not isinstance(data, dict):
            return None
        rows = (((data.get("dividends") or {}).get("rows")) or [])
        history = []
        for row in rows[:12]:
            if not isinstance(row, dict):
                continue
            history.append(
                {
                    "ex_date": row.get("exOrEffDate"),
                    "type": row.get("type"),
                    "amount": _num(row.get("amount")),
                    "declaration_date": row.get("declarationDate"),
                    "payment_date": row.get("paymentDate"),
                }
            )
        return {
            "yield_pct": _num(data.get("yield")),
            "annual_dividend": _num(data.get("annualizedDividend")),
            "payout_ratio": _num(data.get("payoutRatio")),
            "ex_date": data.get("exDividendDate"),
            "payment_date": data.get("dividendPaymentDate"),
            "history": history,
            "source": "nasdaq",
        }

    return await cache.get(key, 24 * 3600, factory)


async def earnings_surprise(symbol: str) -> list[dict[str, Any]]:
    key = f"nasdaq-surprise:{symbol.upper()}"

    async def factory() -> list[dict[str, Any]]:
        data = await _data(f"company/{symbol.upper()}/earnings-surprise")
        table = (data or {}).get("earningsSurpriseTable") if isinstance(data, dict) else None
        rows = (table or {}).get("rows") or []
        results = []
        for row in rows[:8]:
            if not isinstance(row, dict):
                continue
            eps = _num(row.get("eps"))
            consensus = _num(row.get("consensusForecast"))
            surprise = _num(row.get("percentageSurprise"))
            if surprise is None and eps is not None and consensus not in (None, 0):
                surprise = round((eps - consensus) / abs(consensus) * 100, 2)
            results.append(
                {
                    "quarter": row.get("fiscalQtrEnd"),
                    "reported": row.get("dateReported"),
                    "eps": eps,
                    "consensus": consensus,
                    "surprise_pct": surprise,
                }
            )
        return results

    return await cache.get(key, 24 * 3600, factory)


async def earnings_calendar(days: int = 7) -> list[dict[str, Any]]:
    start = datetime.now(ET).date()
    key = f"nasdaq-earnings:{start.isoformat()}:{days}"

    async def factory() -> list[dict[str, Any]]:
        dates = [start + timedelta(days=offset) for offset in range(days)]
        semaphore = asyncio.Semaphore(4)

        async def fetch(day: Any) -> list[dict[str, Any]]:
            async with semaphore:
                data = await _data("calendar/earnings", {"date": day.isoformat()})
                rows = (data or {}).get("rows") if isinstance(data, dict) else None
                results = []
                for row in rows or []:
                    if not isinstance(row, dict):
                        continue
                    cap = _num(row.get("marketCap"))
                    results.append(
                        {
                            "date": day.isoformat(),
                            "time": row.get("time"),
                            "time_label": {
                                "time-pre-market": "盘前",
                                "time-after-hours": "盘后",
                                "time-not-supplied": "待定",
                            }.get(row.get("time"), "待定"),
                            "symbol": str(row.get("symbol") or "").upper(),
                            "name": row.get("name"),
                            "market_cap": cap,
                            "eps_forecast": _num(row.get("epsForecast")),
                            "quarter": row.get("fiscalQuarterEnding"),
                        }
                    )
                results.sort(key=lambda item: item.get("market_cap") or 0, reverse=True)
                return results[:8]

        chunks = await asyncio.gather(*(fetch(day) for day in dates))
        flat = [item for chunk in chunks for item in chunk]
        flat.sort(key=lambda item: (item["date"], -(item.get("market_cap") or 0)))
        return flat[:30]

    return await cache.get(key, 6 * 3600, factory)
