from __future__ import annotations

import asyncio
import html
import json
import logging
import math
import re
import time
from datetime import date, datetime, time as dtime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from server.config import (
    CACHE_DIR,
    EASTMONEY_HEADERS,
    INDEX_CARDS,
    MARKET_HOLIDAYS_2026,
    MARKET_NAMES,
    MARKET_SUFFIX,
    RANGE_MAP,
    SECTOR_ETFS,
    US_MARKETS,
)
from server.data.cache import JsonCache
from server.data.http import UpstreamError, http
from server.data import nasdaq as nasdaq_data
from server.data import tencent as tencent_data

logger = logging.getLogger(__name__)
cache = JsonCache(CACHE_DIR)

_COOLDOWN: dict[str, float] = {}


def _cooling(scope: str) -> bool:
    return time.time() < _COOLDOWN.get(scope, 0)


def _cooldown(scope: str, seconds: float = 180) -> None:
    _COOLDOWN[scope] = time.time() + seconds

PUSH2 = "https://push2.eastmoney.com/api/qt"
PUSH2HIS = "https://push2his.eastmoney.com/api/qt"
# push2 throttles bursts by dropping connections; spreading pages across the
# numbered mirrors keeps the full-market snapshot from silently losing pages.
CLIST_HOSTS = [
    "push2.eastmoney.com",
    "1.push2.eastmoney.com",
    "2.push2.eastmoney.com",
    "7.push2.eastmoney.com",
    "12.push2.eastmoney.com",
    "23.push2.eastmoney.com",
    "44.push2.eastmoney.com",
    "63.push2.eastmoney.com",
    "82.push2.eastmoney.com",
    "99.push2.eastmoney.com",
]
DATACENTER = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
SEARCH_URL = "https://searchadapter.eastmoney.com/api/suggest/get"
SEARCH_TOKEN = "D43BF722C8E33BDC906FB84D85E326E8"
NEWS_SEARCH = "https://search-api-web.eastmoney.com/search/jsonp"
FAST_NEWS = "https://np-listapi.eastmoney.com/comm/web/getFastNewsList"

CLIST_FIELDS = (
    "f2,f3,f5,f6,f9,f12,f13,f14,f20,f21,f23,f24,f25,f100,f115,f133"
)
QUOTE_FIELDS = (
    "f43,f44,f45,f46,f47,f48,f49,f50,f51,f52,f57,f58,f59,f60,f71,"
    "f84,f85,f92,f107,f112,f116,f117,f126,f133,f160,f168,f169,f170,"
    "f171,f172,f174,f175,f179"
)
ET = ZoneInfo("America/New_York")
TAG_RE = re.compile(r"<[^>]+>")


class SymbolNotFound(LookupError):
    pass


def _f(value: Any) -> float | None:
    if value is None or value in ("-", "", "--"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _i(value: Any) -> int | None:
    number = _f(value)
    return int(number) if number is not None else None


def _round(value: Any, digits: int = 2) -> float | None:
    number = _f(value)
    return round(number, digits) if number is not None else None


def _clean_text(value: Any) -> str:
    text = TAG_RE.sub("", str(value or ""))
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def display_symbol(em_symbol: str) -> str:
    return (em_symbol or "").replace("_", ".")


def _is_etf(name: str) -> bool:
    upper = (name or "").upper()
    return "ETF" in upper or "ETP" in upper or "基金" in upper


def _row_stock(row: dict[str, Any]) -> dict[str, Any] | None:
    symbol = str(row.get("f12") or "").strip()
    price = _round(row.get("f2"), 4)
    if not symbol or price is None or price <= 0:
        return None
    market = _i(row.get("f13"))
    name = str(row.get("f14") or symbol)
    return {
        "symbol": display_symbol(symbol),
        "em_symbol": symbol,
        "name": name,
        "market": market,
        "exchange": MARKET_NAMES.get(market, "US"),
        "price": price,
        "change": _round(row.get("f4"), 4),
        "change_pct": _round(row.get("f3"), 4),
        "volume": _i(row.get("f5")),
        "amount": _f(row.get("f6")),
        "pe": _round(row.get("f9") if row.get("f9") not in (None, "-") else row.get("f115")),
        "pb": _round(row.get("f23")),
        "market_cap": _f(row.get("f20")),
        "float_cap": _f(row.get("f21")),
        "chg_60d": _round(row.get("f24")),
        "chg_ytd": _round(row.get("f25")),
        "industry": str(row.get("f100") or "其他"),
        "dividend_yield": _round(row.get("f133")),
        "is_etf": _is_etf(name),
    }


def _quote_from_push(data: dict[str, Any], em_symbol: str | None = None) -> dict[str, Any]:
    # The quote endpoint is called with fltt=2, so every price field is already
    # scaled to a decimal string (f59 is metadata only and must not be applied).
    symbol = str(data.get("f57") or em_symbol or "")
    price = _f(data.get("f43"))
    if price is None:
        raise UpstreamError("quote unavailable")
    market = _i(data.get("f107")) or 0
    name = str(data.get("f58") or symbol)
    return {
        "symbol": display_symbol(symbol),
        "em_symbol": symbol,
        "name": name,
        "market": market,
        "exchange": str(data.get("f112") or MARKET_NAMES.get(market, "US")),
        "currency": str(data.get("f172") or "USD"),
        "decimal": _i(data.get("f59")) or 2,
        "price": price,
        "open": _f(data.get("f46")),
        "high": _f(data.get("f44")),
        "low": _f(data.get("f45")),
        "prev_close": _f(data.get("f60")),
        "change": _f(data.get("f169")),
        "change_pct": _f(data.get("f170")),
        "amplitude": _f(data.get("f171")),
        "turnover": _f(data.get("f168")),
        "volume": _i(data.get("f47")),
        "amount": _f(data.get("f48")),
        "avg_price": _f(data.get("f71")),
        "market_cap": _f(data.get("f116")),
        "float_cap": _f(data.get("f117")),
        "shares_outstanding": _f(data.get("f84")),
        "eps_ttm": _round(data.get("f160"), 4),
        "eps_last_fy": _round(data.get("f92"), 4),
        "dividend_yield": _round(data.get("f126") if data.get("f126") not in (None, 0) else data.get("f133")),
        "week52_high": _f(data.get("f174") or data.get("f51")),
        "week52_low": _f(data.get("f175") or data.get("f52")),
        "is_etf": _is_etf(name),
        "pe": None,
        "pb": None,
        "source": "eastmoney",
    }


def _params(**kwargs: Any) -> dict[str, Any]:
    return {key: value for key, value in kwargs.items() if value is not None}


async def _stock_get(secid: str, fields: str = QUOTE_FIELDS) -> dict[str, Any] | None:
    payload = await http.get_json(
        f"{PUSH2}/stock/get",
        params={"secid": secid, "fields": fields, "fltt": 2, "invt": 2},
        headers=EASTMONEY_HEADERS,
    )
    if not isinstance(payload, dict) or payload.get("rc") not in (0, None):
        return None
    data = payload.get("data")
    return data if isinstance(data, dict) else None


async def search_us(query: str, limit: int = 12) -> list[dict[str, Any]]:
    query = (query or "").strip()
    if not query:
        return []
    payload = await http.get_json(
        SEARCH_URL,
        params={
            "input": query,
            "type": 14,
            "token": SEARCH_TOKEN,
            "count": max(limit, 8),
        },
        headers=EASTMONEY_HEADERS,
    )
    rows = (
        ((payload or {}).get("QuotationCodeTable") or {}).get("Data") or []
        if isinstance(payload, dict)
        else []
    )
    results: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("Classify") != "UsStock":
            continue
        code = str(row.get("Code") or "").strip()
        if not code:
            continue
        market = _i(row.get("MktNum"))
        us_type = str(row.get("TypeUS") or "")
        name = str(row.get("Name") or code)
        results.append(
            {
                "symbol": display_symbol(code),
                "em_symbol": code,
                "name": name,
                "exchange": str(row.get("JYS") or MARKET_NAMES.get(market, "US")),
                "market": market,
                "secid": f"{market}.{code}",
                "kind": "ETF" if us_type == "5" or _is_etf(name) else "股票",
                "us_type": us_type,
            }
        )
    preferred = [item for item in results if item["us_type"] in {"1", "5"}]
    return (preferred or results)[:limit]


async def resolve(query: str) -> dict[str, Any]:
    raw = (query or "").strip()
    if not raw:
        raise SymbolNotFound("empty symbol")
    if not re.fullmatch(r"[A-Za-z0-9._\-]{1,16}", raw):
        # Chinese company names are valid search terms, but direct resolution needs a code.
        results = await search_us(raw, limit=8)
        if not results:
            raise SymbolNotFound(f"未找到 {raw}")
        raw = results[0]["em_symbol"]
    key = f"resolve:v2:{raw.upper()}"
    ttl = 7 * 24 * 3600

    async def factory() -> dict[str, Any]:
        results = await search_us(raw, limit=12)
        wanted = raw.upper()
        wanted_em = wanted.replace(".", "_")
        exact = [
            item
            for item in results
            if item["em_symbol"].upper() == wanted_em or item["symbol"].upper() == wanted
        ]
        if exact:
            exact.sort(key=lambda item: 0 if item["us_type"] == "1" else 1)
            return exact[0]
        if results:
            return results[0]

        variants: list[str] = []
        for candidate in (
            raw.upper(),
            raw.upper().replace(".", "_"),
            raw.upper().replace(".", "-"),
            raw.upper().replace("-", "_"),
        ):
            if candidate not in variants:
                variants.append(candidate)
        for variant in variants:
            for market in US_MARKETS:
                data = await _stock_get(f"{market}.{variant}", "f43,f57,f58,f59,f107,f112")
                if data and data.get("f57"):
                    return {
                        "symbol": display_symbol(str(data["f57"])),
                        "em_symbol": str(data["f57"]),
                        "name": str(data.get("f58") or data["f57"]),
                        "exchange": str(data.get("f112") or MARKET_NAMES.get(market, "US")),
                        "market": market,
                        "secid": f"{market}.{variant}",
                        "kind": "ETF" if _is_etf(str(data.get("f58") or "")) else "股票",
                        "us_type": "5" if _is_etf(str(data.get("f58") or "")) else "1",
                    }
        raise SymbolNotFound(f"未找到美股代码 {raw}")

    return await cache.get(key, ttl, factory)


async def quote_by_secid(secid: str, em_symbol: str | None = None) -> dict[str, Any]:
    key = f"quote:v3:{secid}"
    if _cooling("quote"):
        raise UpstreamError("eastmoney quote endpoint cooling down")

    async def factory() -> dict[str, Any]:
        try:
            data = await _stock_get(secid)
        except Exception:
            _cooldown("quote")
            raise
        if not data:
            raise UpstreamError(f"quote unavailable for {secid}")
        return _quote_from_push(data, em_symbol)

    try:
        return await cache.get(key, 30, factory, persist=False)
    except UpstreamError:
        _cooldown("quote")
        raise


async def _quote_core(symbol: str) -> dict[str, Any]:
    info = await resolve(symbol)
    result = await quote_by_secid(info["secid"], info["em_symbol"])
    result["name"] = info.get("name") or result["name"]
    result["kind"] = info.get("kind", "股票")
    return result


async def quote(symbol: str) -> dict[str, Any]:
    try:
        return await _quote_core(symbol)
    except Exception as exc:
        logger.info("eastmoney quote failed for %s: %s", symbol, exc)
    alt = await tencent_data.quote(symbol)
    alt["kind"] = "ETF" if alt.get("is_etf") else "股票"
    return alt


async def quotes(symbols: list[str]) -> list[dict[str, Any]]:
    requested = list(dict.fromkeys(item.strip().upper() for item in symbols if item.strip()))[:24]
    if not requested:
        return []
    if _cooling("quote"):
        try:
            return await tencent_data.quotes(requested)
        except Exception as exc:
            logger.info("tencent bulk quotes failed: %s", exc)
            return []
    semaphore = asyncio.Semaphore(8)

    async def one(symbol: str) -> dict[str, Any] | None:
        async with semaphore:
            try:
                return await _quote_core(symbol)
            except Exception as exc:  # partial results are still useful
                logger.info("quote failed for %s: %s", symbol, exc)
                return None

    results = [item for item in await asyncio.gather(*(one(item) for item in requested)) if item]
    found = {item["symbol"] for item in results}
    missing = [symbol for symbol in requested if symbol not in found]
    if missing:
        try:
            results.extend(await tencent_data.quotes(missing))
        except Exception as exc:
            logger.info("tencent fallback quotes failed: %s", exc)
    return results


async def _clist_page(
    page: int,
    *,
    field: str = "f20",
    order: int = 1,
    page_size: int = 100,
    host: str = "push2.eastmoney.com",
    retries: int = 1,
    timeout: float | None = None,
) -> tuple[list[dict[str, Any]], int]:
    payload = await http.get_json(
        f"https://{host}/api/qt/clist/get",
        params={
            "pn": page,
            "pz": page_size,
            "po": order,
            "np": 1,
            "fltt": 2,
            "invt": 2,
            "fid": field,
            "fs": "m:105,m:106,m:107",
            "fields": CLIST_FIELDS,
        },
        headers=EASTMONEY_HEADERS,
        retries=retries,
        timeout=timeout,
    )
    data = (payload or {}).get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return [], 0
    diff = data.get("diff") or []
    if isinstance(diff, dict):
        diff = list(diff.values())
    return [row for row in diff if isinstance(row, dict)], int(data.get("total") or 0)


async def _stale_universe_snapshot(limit: int) -> dict[str, Any] | None:
    keys = [f"universe:v5:{limit}", f"universe:v4:{limit}"]
    if limit != 3000:
        keys.extend(("universe:v5:3000", "universe:v4:3000"))
    for key in keys:
        value = await asyncio.to_thread(cache.read_stale, key)
        if (
            isinstance(value, dict)
            and value.get("source") == "eastmoney"
            and value.get("items")
        ):
            return value
    return None


def _merge_universe_items(
    primary: list[dict[str, Any]],
    extra: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in primary + extra:
        symbol = str(item.get("symbol") or "").upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        merged.append(item)
    merged.sort(key=lambda item: item.get("market_cap") or 0, reverse=True)
    return merged[:limit]


async def universe(limit: int = 3000) -> dict[str, Any]:
    limit = max(300, min(int(limit), 15000))
    key = f"universe:v5:{limit}"
    ttl = 20 * 60

    async def factory() -> dict[str, Any]:
        if _cooling("clist"):
            raise UpstreamError("eastmoney snapshot endpoint cooling down")
        semaphore = asyncio.Semaphore(4)
        host_lock = asyncio.Lock()
        host_cursor = 0

        async def pick_host() -> str:
            nonlocal host_cursor
            async with host_lock:
                host = CLIST_HOSTS[host_cursor % len(CLIST_HOSTS)]
                host_cursor += 1
                return host

        async def fetch(
            page: int,
            tries: int = 3,
            size: int = 100,
            timeout: float | None = None,
        ) -> tuple[list[dict[str, Any]], int] | None:
            async with semaphore:
                for attempt in range(tries):
                    host = await pick_host()
                    try:
                        await asyncio.sleep(0.1 + attempt * 0.25)
                        rows, total = await _clist_page(
                            page,
                            host=host,
                            page_size=size,
                            retries=0,
                            timeout=timeout,
                        )
                        if rows:
                            return rows, total
                    except Exception as exc:
                        logger.info("universe page %s failed on %s (%s)", page, host, exc)
                return None

        started = time.time()
        probe = None
        probe_size = 100
        candidates = (
            [(5000, 8.0), (100, 5.0)]
            if limit > 3000
            else [(100, None)]
        )
        for size, timeout in candidates:
            probe = await fetch(1, tries=1, size=size, timeout=timeout)
            if probe is not None:
                probe_size = size
                break
        if probe is None:
            _cooldown("clist", 90)
            raise UpstreamError("universe snapshot head unavailable")

        probe_rows, total_market = probe
        if total_market > len(probe_rows) and len(probe_rows) < probe_size:
            # Upstream caps pz below the requested page size.
            probe_size = max(100, len(probe_rows))
        elif total_market and total_market <= len(probe_rows):
            probe_size = max(1, len(probe_rows))
        pages = max(1, math.ceil(limit / probe_size))
        page_numbers = list(range(1, pages + 1))
        results = [probe] + list(
            await asyncio.gather(*(fetch(page, size=probe_size) for page in page_numbers[1:]))
        )
        missing = [page for page, result in zip(page_numbers, results) if result is None]
        if missing:
            retries = await asyncio.gather(
                *(fetch(page, tries=3, size=probe_size) for page in missing)
            )
            for page, result in zip(missing, retries):
                results[page - 1] = result
            missing = [page for page, result in zip(page_numbers, results) if result is None]
        # The first pages hold every mega cap; an incomplete head is unusable.
        if any(page <= 10 for page in missing):
            _cooldown("clist", 90)
            raise UpstreamError(f"universe snapshot incomplete: pages {missing[:10]} unavailable")
        if missing:
            logger.warning(
                "universe snapshot partial: %s/%s pages missing (%s)",
                len(missing),
                pages,
                missing,
            )

        total_market = max((result[1] for result in results if result), default=0)
        seen: set[tuple[str, int | None]] = set()
        items: list[dict[str, Any]] = []
        for result in results:
            if not result:
                continue
            for row in result[0]:
                stock = _row_stock(row)
                if not stock:
                    continue
                identity = (stock["em_symbol"], stock["market"])
                if identity in seen:
                    continue
                seen.add(identity)
                items.append(stock)
        if len(items) < 300:
            _cooldown("clist", 90)
            raise UpstreamError("universe snapshot too small")
        items.sort(key=lambda item: item.get("market_cap") or 0, reverse=True)
        items = items[:limit]
        logger.info(
            "universe refreshed: %s rows in %.1fs (%s pages x %s, missing: %s)",
            len(items),
            time.time() - started,
            pages,
            probe_size,
            missing or "none",
        )
        return {
            "items": items,
            "limit": limit,
            "total_market": total_market or len(items),
            "source": "eastmoney",
            "updated_at": datetime.now(ET).isoformat(),
        }

    try:
        return await cache.get(key, ttl, factory)
    except UpstreamError as exc:
        logger.warning("eastmoney universe unavailable (%s); using fallback", exc)
        stale = await _stale_universe_snapshot(limit)
        items = await nasdaq_data.screener_universe(limit)
        if stale and items:
            merged = _merge_universe_items(stale.get("items") or [], items, limit)
            return {
                "items": merged,
                "limit": limit,
                "total_market": stale.get("total_market") or len(merged),
                "source": "eastmoney+nasdaq",
                "updated_at": stale.get("updated_at") or datetime.now(ET).isoformat(),
            }
        if stale:
            return {
                **stale,
                "items": (stale.get("items") or [])[:limit],
                "limit": limit,
            }
        if not items:
            raise
        return {
            "items": items[:limit],
            "limit": limit,
            "total_market": len(items),
            "source": "nasdaq_screener",
            "updated_at": datetime.now(ET).isoformat(),
        }


async def movers() -> dict[str, list[dict[str, Any]]]:
    def clean(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = []
        for stock in rows:
            if not stock or stock.get("is_etf"):
                continue
            if (stock.get("market_cap") or 0) < 1e9 or (stock.get("price") or 0) < 2:
                continue
            result.append(stock)
        return result

    async def from_snapshot() -> dict[str, list[dict[str, Any]]]:
        data = await universe(3000)
        items = clean(data.get("items") or [])
        return {
            "gainers": sorted(items, key=lambda item: item.get("change_pct") or 0, reverse=True)[:8],
            "losers": sorted(items, key=lambda item: item.get("change_pct") or 0)[:8],
            "active": sorted(items, key=lambda item: item.get("amount") or 0, reverse=True)[:8],
        }

    async def factory() -> dict[str, list[dict[str, Any]]]:
        if _cooling("clist"):
            return await from_snapshot()
        try:
            gainers_pages, losers_pages, active_pages = await asyncio.gather(
                asyncio.gather(*(_clist_page(page, field="f3", order=1) for page in (1, 2, 3))),
                asyncio.gather(*(_clist_page(page, field="f3", order=0) for page in (1, 2, 3))),
                asyncio.gather(*(_clist_page(page, field="f6", order=1) for page in (1, 2))),
            )
        except Exception as exc:
            logger.info("eastmoney movers failed: %s", exc)
            _cooldown("clist")
            return await from_snapshot()
        gainers_rows = [row for rows, _ in gainers_pages for row in rows]
        losers_rows = [row for rows, _ in losers_pages for row in rows]
        active_rows = [row for rows, _ in active_pages for row in rows]
        result = {
            "gainers": clean([_row_stock(row) for row in gainers_rows])[:8],
            "losers": clean([_row_stock(row) for row in losers_rows])[:8],
            "active": clean([_row_stock(row) for row in active_rows])[:8],
        }
        if not result["gainers"] and not result["losers"] and not result["active"]:
            return await from_snapshot()
        return result

    return await cache.get("movers:v3", 120, factory)


async def sector_performance() -> list[dict[str, Any]]:
    async def factory() -> list[dict[str, Any]]:
        mapping = {item["symbol"]: item for item in SECTOR_ETFS}
        if not _cooling("ulist"):
            try:
                payload = await http.get_json(
                    f"{PUSH2}/ulist.np/get",
                    params={
                        "fltt": 2,
                        "invt": 2,
                        "fields": "f2,f3,f4,f6,f12,f13,f14,f24,f25",
                        "secids": ",".join(item["secid"] for item in SECTOR_ETFS),
                    },
                    headers=EASTMONEY_HEADERS,
                )
                rows = (((payload or {}).get("data") or {}).get("diff") or []) if isinstance(payload, dict) else []
                result = []
                for row in rows:
                    symbol = str(row.get("f12") or "")
                    meta = mapping.get(symbol)
                    if not meta:
                        continue
                    result.append(
                        {
                            "symbol": symbol,
                            "name": meta["name"],
                            "etf_name": str(row.get("f14") or symbol),
                            "price": _round(row.get("f2"), 4),
                            "change_pct": _round(row.get("f3")),
                            "change": _round(row.get("f4")),
                            "amount": _f(row.get("f6")),
                            "chg_60d": _round(row.get("f24")),
                            "chg_ytd": _round(row.get("f25")),
                            "source": "eastmoney",
                        }
                    )
                if result:
                    result.sort(key=lambda item: item.get("change_pct") or 0, reverse=True)
                    return result
            except Exception as exc:
                logger.info("eastmoney sectors failed: %s", exc)
                _cooldown("ulist")
        alt = await tencent_data.quotes([item["symbol"] for item in SECTOR_ETFS])
        result = []
        for item in alt:
            meta = mapping.get(item["symbol"])
            if not meta:
                continue
            result.append(
                {
                    "symbol": item["symbol"],
                    "name": meta["name"],
                    "etf_name": item.get("name") or item["symbol"],
                    "price": _round(item.get("price"), 4),
                    "change_pct": _round(item.get("change_pct")),
                    "change": _round(item.get("change")),
                    "amount": item.get("amount"),
                    "chg_60d": None,
                    "chg_ytd": None,
                    "source": "tencent",
                }
            )
        if not result:
            raise UpstreamError("sector performance unavailable")
        result.sort(key=lambda item: item.get("change_pct") or 0, reverse=True)
        return result

    return await cache.get("sectors:v3", 300, factory)


async def indices() -> list[dict[str, Any]]:
    async def factory() -> list[dict[str, Any]]:
        mapping = {item["symbol"]: item for item in INDEX_CARDS}
        order = {item["symbol"]: idx for idx, item in enumerate(INDEX_CARDS)}
        if not _cooling("ulist"):
            try:
                payload = await http.get_json(
                    f"{PUSH2}/ulist.np/get",
                    params={
                        "fltt": 2,
                        "invt": 2,
                        "fields": "f2,f3,f4,f6,f12,f13,f14",
                        "secids": ",".join(item["secid"] for item in INDEX_CARDS),
                    },
                    headers=EASTMONEY_HEADERS,
                )
                rows = (((payload or {}).get("data") or {}).get("diff") or []) if isinstance(payload, dict) else []
                by_em_symbol = {
                    item["secid"].split(".", 1)[1]: item for item in INDEX_CARDS
                }
                result = []
                for row in rows:
                    em_symbol = str(row.get("f12") or "")
                    meta = by_em_symbol.get(em_symbol)
                    if not meta:
                        continue
                    result.append(
                        {
                            "symbol": meta["symbol"],
                            "name": meta["name"],
                            "price": _round(row.get("f2"), 2),
                            "change": _round(row.get("f4"), 2),
                            "change_pct": _round(row.get("f3")),
                            "kind": meta["kind"],
                            "source": "eastmoney",
                        }
                    )
                if result:
                    result.sort(key=lambda item: order.get(item["symbol"], 99))
                    return result
            except Exception as exc:
                logger.info("eastmoney indices failed: %s", exc)
                _cooldown("ulist")
        alt = await tencent_data.index_quotes()
        result = []
        for item in alt:
            meta = mapping.get(item["symbol"])
            if not meta:
                continue
            result.append(
                {
                    "symbol": item["symbol"],
                    "name": meta["name"],
                    "price": _round(item.get("price"), 2),
                    "change": _round(item.get("change"), 2),
                    "change_pct": _round(item.get("change_pct")),
                    "kind": meta["kind"],
                    "source": "tencent",
                }
            )
        if not result:
            raise UpstreamError("indices unavailable")
        result.sort(key=lambda item: order.get(item["symbol"], 99))
        return result

    return await cache.get("indices:v3", 45, factory)


async def trends(secid: str) -> dict[str, list[Any]]:
    payload = await http.get_json(
        f"{PUSH2HIS}/stock/trends2/get",
        params={
            "secid": secid,
            "ndays": 1,
            "iscr": 0,
            "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
        },
        headers=EASTMONEY_HEADERS,
    )
    data = (payload or {}).get("data") if isinstance(payload, dict) else None
    lines = (data or {}).get("trends") or []
    times: list[str] = []
    closes: list[float] = []
    for line in lines:
        parts = str(line).split(",")
        if len(parts) < 3:
            continue
        close = _f(parts[2])
        if close is None:
            continue
        times.append(parts[0])
        closes.append(close)
    return {"t": times, "c": closes}


async def index_trends() -> dict[str, list[float]]:
    proxy_map = {"SPX": "SPY", "COMP": "QQQ", "DJIA": "DIA", "IWM": "IWM"}
    etf_secids = {"SPX": "107.SPY", "COMP": "107.QQQ", "DJIA": "107.DIA", "IWM": "107.IWM"}

    async def factory() -> dict[str, list[float]]:
        async def one(item: dict[str, Any]) -> tuple[str, list[float]]:
            try:
                data = await asyncio.wait_for(trends(item["secid"]), timeout=2.0)
                return item["symbol"], data["c"][-90:]
            except Exception as exc:
                logger.info("trend failed for %s: %s", item["symbol"], exc)
                return item["symbol"], []

        pairs = dict(await asyncio.gather(*(one(item) for item in INDEX_CARDS)))

        async def daily(secid: str) -> list[float]:
            try:
                payload = await asyncio.wait_for(
                    http.get_json(
                        f"{PUSH2HIS}/stock/kline/get",
                        params={
                            "secid": secid,
                            "klt": 101,
                            "fqt": 1,
                            "lmt": 60,
                            "end": "20500101",
                            "fields1": "f1,f2,f3,f4,f5,f6",
                            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                        },
                        headers=EASTMONEY_HEADERS,
                    ),
                    timeout=4.0,
                )
                lines = ((payload or {}).get("data") or {}).get("klines") or []
                closes: list[float] = []
                for line in lines:
                    parts = str(line).split(",")
                    if len(parts) < 3:
                        continue
                    close = _f(parts[2])
                    if close is not None:
                        closes.append(close)
                return closes[-60:]
            except Exception as exc:
                logger.info("index kline failed for %s: %s", secid, exc)
                return []

        async def proxy(symbol: str) -> list[float]:
            try:
                bars = await asyncio.wait_for(
                    nasdaq_data.historical(proxy_map[symbol], 80), timeout=4.0
                )
                return [float(bar["c"]) for bar in bars][-60:]
            except Exception as exc:
                logger.info("index proxy failed for %s: %s", symbol, exc)
                return []

        async def fill(item: dict[str, Any]) -> tuple[str, list[float]]:
            daily_values, proxy_values = await asyncio.gather(
                daily(etf_secids[item["symbol"]]), proxy(item["symbol"])
            )
            return item["symbol"], daily_values or proxy_values

        missing = [item for item in INDEX_CARDS if not pairs.get(item["symbol"])]
        if missing:
            pairs.update(dict(await asyncio.gather(*(fill(item) for item in missing))))
        return pairs

    return await cache.get("index-trends:v6", 120, factory)


FALLBACK_DAYS = {
    "1M": 40,
    "3M": 100,
    "6M": 200,
    "YTD": 330,
    "1Y": 400,
    "3Y": 1100,
    "5Y": 1800,
    "MAX": 2600,
}


async def _nasdaq_candles(
    info: dict[str, Any], timeframe: str, settings: dict[str, Any], *, warmup: int = 0
) -> dict[str, Any]:
    days = FALLBACK_DAYS.get(timeframe, 400)
    history = await nasdaq_data.historical(info["symbol"], days + warmup * 2)
    bars = history
    if warmup and timeframe in {"YTD", "MAX"}:
        # Unbounded ranges retain the original date window, excluding extra warmup history.
        start = (datetime.now(ET) - timedelta(days=max(days, 30) + 30)).strftime("%Y-%m-%d")
        bars = [bar for bar in bars if str(bar["t"])[:10] >= start][-days:]
    if timeframe == "YTD":
        year = str(datetime.now(ET).year)
        bars = [bar for bar in history if str(bar["t"])[:4] == year] or bars
    limits = {
        "1D": 2,
        "5D": 6,
        "1M": 24,
        "3M": 68,
        "6M": 135,
        "1Y": 260,
        "3Y": 780,
        "5Y": 1300,
    }
    limit = limits.get(timeframe)
    if limit:
        bars = bars[-limit:]
    if not bars:
        raise UpstreamError(f"no fallback candles for {info['symbol']}")
    result = {
        "symbol": info["symbol"],
        "name": info["name"],
        "secid": info["secid"],
        "range": timeframe,
        "intraday": False,
        "interval": "1d",
        "price_basis": "raw",
        "bars": bars,
        "source": "nasdaq",
        "degraded": True,
        "note": "东方财富历史行情暂不可用，已切换至 Nasdaq 日线数据。",
    }
    if warmup:
        result["warmup_bars"] = [bar for bar in history if str(bar["t"]) < str(bars[0]["t"])][-warmup:]
    return result


async def candles(symbol: str, timeframe: str = "1Y", *, warmup: int = 0) -> dict[str, Any]:
    timeframe = (timeframe or "1Y").upper()
    if timeframe not in RANGE_MAP:
        raise ValueError(f"unsupported range {timeframe}")
    warmup = max(0, int(warmup))
    info = await resolve(symbol)
    settings = RANGE_MAP[timeframe]
    key = f"candles:v5:{info['secid']}:{timeframe}:{warmup}"
    ttl = 120 if settings["intraday"] else 600

    async def factory() -> dict[str, Any]:
        lines: list[Any] = []
        if not _cooling("kline"):
            try:
                payload = await http.get_json(
                    f"{PUSH2HIS}/stock/kline/get",
                    params={
                        "secid": info["secid"],
                        "klt": settings["klt"],
                        "fqt": 1,
                        "lmt": settings["lmt"] + warmup,
                        "end": "20500101",
                        "fields1": "f1,f2,f3,f4,f5,f6",
                        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                    },
                    headers=EASTMONEY_HEADERS,
                )
                data = (payload or {}).get("data") if isinstance(payload, dict) else None
                lines = (data or {}).get("klines") or []
            except Exception as exc:
                logger.info("eastmoney kline failed for %s: %s", symbol, exc)
                _cooldown("kline")
        if lines:
            bars: list[dict[str, Any]] = []
            for line in lines:
                parts = str(line).split(",")
                if len(parts) < 7:
                    continue
                bar = {
                    "t": parts[0],
                    "o": _f(parts[1]),
                    "c": _f(parts[2]),
                    "h": _f(parts[3]),
                    "l": _f(parts[4]),
                    "v": _f(parts[5]),
                    "a": _f(parts[6]),
                    "chg": _f(parts[8]) if len(parts) > 8 else None,
                }
                if None not in (bar["o"], bar["c"], bar["h"], bar["l"]):
                    bars.append(bar)
            history = bars
            bars = history[-settings["lmt"]:]
            if timeframe == "YTD":
                year = str(datetime.now(ET).year)
                bars = [bar for bar in history if str(bar["t"])[:4] == year] or bars
            if bars:
                result = {
                    "symbol": info["symbol"],
                    "name": info["name"],
                    "secid": info["secid"],
                    "range": timeframe,
                    "intraday": bool(settings["intraday"]),
                    "interval": {5: "5m", 15: "15m", 101: "1d", 102: "1w"}[settings["klt"]],
                    "price_basis": "forward_adjusted",
                    "bars": bars,
                    "source": "eastmoney",
                    "degraded": False,
                }
                if warmup:
                    result["warmup_bars"] = [
                        bar for bar in history if str(bar["t"]) < str(bars[0]["t"])
                    ][-warmup:]
                return result
        if timeframe == "1D" and not _cooling("kline"):
            try:
                trend = await trends(info["secid"])
                bars = [
                    {"t": stamp, "c": close, "v": None}
                    for stamp, close in zip(trend["t"], trend["c"])
                ]
                if bars:
                    result = {
                        "symbol": info["symbol"],
                        "name": info["name"],
                        "secid": info["secid"],
                        "range": timeframe,
                        "intraday": True,
                        "interval": "1m",
                        "price_basis": "raw",
                        "bars": bars,
                        "source": "eastmoney_trends",
                        "degraded": False,
                    }
                    if warmup:
                        result["warmup_bars"] = []
                    return result
            except Exception as exc:
                logger.info("eastmoney trends failed for %s: %s", symbol, exc)
        return await _nasdaq_candles(info, timeframe, settings, warmup=warmup)

    return await cache.get(key, ttl, factory, persist=False)


async def _datacenter(report_name: str, flt: str, *, page_size: int = 20, sort: bool = True) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "reportName": report_name,
        "columns": "ALL",
        "filter": flt,
        "pageNumber": 1,
        "pageSize": page_size,
    }
    if sort:
        params["sortTypes"] = -1
        params["sortColumns"] = "REPORT_DATE"
    payload = await http.get_json(DATACENTER, params=params, headers=EASTMONEY_HEADERS)
    result = (payload or {}).get("result") if isinstance(payload, dict) else None
    data = (result or {}).get("data") if isinstance(result, dict) else None
    return [row for row in data or [] if isinstance(row, dict)]


async def _secucode(em_symbol: str, market: int | None) -> str | None:
    key = f"secucode:v2:{em_symbol}:{market}"
    candidates: list[str] = []
    primary = MARKET_SUFFIX.get(market or 0)
    if primary:
        candidates.append(primary)
    for suffix in ("O", "N", "A"):
        if suffix not in candidates:
            candidates.append(suffix)

    async def factory() -> str | None:
        for suffix in candidates:
            try:
                rows = await _datacenter(
                    "RPT_USF10_INFO_ORGPROFILE",
                    f'(SECUCODE="{em_symbol}.{suffix}")',
                    page_size=1,
                    sort=False,
                )
            except Exception:
                continue
            if rows:
                return f"{em_symbol}.{suffix}"
        return None

    return await cache.get(key, 7 * 24 * 3600, factory)


async def profile(symbol: str) -> dict[str, Any] | None:
    info = await resolve(symbol)
    if info.get("kind") == "ETF":
        return None
    secucode = await _secucode(info["em_symbol"], info.get("market"))

    async def factory() -> dict[str, Any] | None:
        if not secucode:
            return None
        rows = await _datacenter(
            "RPT_USF10_INFO_ORGPROFILE",
            f'(SECUCODE="{secucode}")',
            page_size=1,
            sort=False,
        )
        if not rows:
            return None
        row = rows[0]
        return {
            "symbol": info["symbol"],
            "name_cn": str(row.get("SECURITY_NAME_ABBR") or info["name"]),
            "name_en": str(row.get("ORG_EN_ABBR") or row.get("ORG_NAME") or info["name"]),
            "org_name": str(row.get("ORG_NAME") or ""),
            "industry": str(row.get("BELONG_INDUSTRY") or ""),
            "founded": str(row.get("FOUND_DATE") or "")[:10],
            "market": str(row.get("BELONG_MARKET") or ""),
            "chairman": str(row.get("CHAIRMAN") or ""),
            "location": str(row.get("REG_PLACE") or ""),
            "address": str(row.get("ADDRESS") or ""),
            "fiscal_year_end": str(row.get("YEAR_SETTLE_DAY") or ""),
            "employees": _i(row.get("EMP_NUM")),
            "phone": str(row.get("ORG_TEL") or ""),
            "website": str(row.get("ORG_WEB") or ""),
            "country": str(row.get("COUNTRY") or ""),
            "isin": str(row.get("ISIN_CODE") or ""),
            "description": _clean_text(row.get("ORG_PROFILE") or ""),
            "source": "eastmoney_f10",
        }

    return await cache.get(f"profile:v2:{info['secid']}", 7 * 24 * 3600, factory)


def _indicator_period(row: dict[str, Any], period_type: str) -> dict[str, Any]:
    return {
        "date": str(row.get("REPORT_DATE") or "")[:10],
        "type": period_type,
        "revenue": _f(row.get("OPERATE_INCOME")),
        "revenue_yoy": _round(row.get("OPERATE_INCOME_YOY")),
        "gross_profit": _f(row.get("GROSS_PROFIT")),
        "gross_profit_yoy": _round(row.get("GROSS_PROFIT_YOY")),
        "net_profit": _f(row.get("PARENT_HOLDER_NETPROFIT")),
        "net_profit_yoy": _round(row.get("PARENT_HOLDER_NETPROFIT_YOY")),
        "eps": _round(row.get("DILUTED_EPS") if row.get("DILUTED_EPS") is not None else row.get("BASIC_EPS"), 4),
        "gross_margin": _round(row.get("GROSS_PROFIT_RATIO")),
        "net_margin": _round(row.get("NET_PROFIT_RATIO")),
        "roe": _round(row.get("ROE_AVG")),
        "roa": _round(row.get("ROA")),
        "current_ratio": _round(row.get("CURRENT_RATIO")),
        "quick_ratio": _round(row.get("SPEED_RATIO")),
        "debt_ratio": _round(row.get("DEBT_ASSET_RATIO")),
        "equity_ratio": _round(row.get("EQUITY_RATIO")),
        "ocf_to_debt": _round(row.get("OCF_LIQDEBT")),
        "asset_turnover": _round(row.get("TOTAL_ASSETS_TR")),
        "receivable_days": _round(row.get("ACCOUNTS_RECE_TDAYS")),
        "inventory_days": _round(row.get("INVENTORY_TDAYS")),
    }


async def _income_fallback(secucode: str) -> dict[str, Any]:
    raw = await _datacenter(
        "RPT_USF10_FN_INCOME",
        f'(SECUCODE="{secucode}")',
        page_size=220,
        sort=True,
    )
    groups: dict[str, dict[str, Any]] = {}
    for row in raw:
        if row.get("REPORT_TYPE") != "单季报":
            continue
        date_value = str(row.get("REPORT_DATE") or "")[:10]
        if not date_value:
            continue
        group = groups.setdefault(date_value, {"date": date_value, "type": "quarter"})
        name = str(row.get("ITEM_NAME") or "")
        amount = _f(row.get("AMOUNT"))
        if amount is None:
            continue
        if name in {"收入总额", "营业收入", "主营收入"} and group.get("revenue") is None:
            group["revenue"] = amount
        elif name in {"归属于母公司股东净利润", "归属于普通股股东净利润", "净利润"} and group.get("net_profit") is None:
            group["net_profit"] = amount
        elif name == "毛利" and group.get("gross_profit") is None:
            group["gross_profit"] = amount
        elif name.startswith("摊薄每股收益") and group.get("eps") is None:
            group["eps"] = round(amount, 4)
        elif name == "营业利润" and group.get("operating_income") is None:
            group["operating_income"] = amount
    quarterly = []
    for group in groups.values():
        revenue = group.get("revenue")
        net_profit = group.get("net_profit")
        gross_profit = group.get("gross_profit")
        if revenue is None and net_profit is None:
            continue
        quarterly.append(
            {
                **group,
                "gross_margin": round(gross_profit / revenue * 100, 2) if gross_profit and revenue else None,
                "net_margin": round(net_profit / revenue * 100, 2) if net_profit and revenue else None,
                "fallback": True,
            }
        )
    quarterly.sort(key=lambda item: item["date"], reverse=True)
    return {
        "annual": [],
        "quarterly": quarterly[:8],
        "currency": "USD",
        "source": "eastmoney_f10_income",
        "fallback": True,
        "note": "该公司所属行业无标准主指标，财务数据来自利润表（单季）。",
    }


async def financials(symbol: str) -> dict[str, Any]:
    info = await resolve(symbol)
    key = f"financials:v2:{info['secid']}"
    secucode = await _secucode(info["em_symbol"], info.get("market"))

    async def factory() -> dict[str, Any]:
        if not secucode:
            return {
                "annual": [],
                "quarterly": [],
                "currency": "USD",
                "source": "eastmoney_f10",
                "fallback": False,
                "note": "ETF 无公司财务数据。",
            }
        rows = await _datacenter(
            "RPT_USF10_FN_GMAININDICATOR",
            f'(SECUCODE="{secucode}")',
            page_size=72,
        )
        annual: list[dict[str, Any]] = []
        quarterly: list[dict[str, Any]] = []
        currency = "USD"
        for row in rows:
            date_type = str(row.get("DATE_TYPE") or "")
            currency = str(row.get("CURRENCY") or currency)
            if date_type == "年报":
                annual.append(_indicator_period(row, "annual"))
            elif date_type == "单季报":
                quarterly.append(_indicator_period(row, "quarter"))
        annual.sort(key=lambda item: item["date"], reverse=True)
        quarterly.sort(key=lambda item: item["date"], reverse=True)
        if not annual and not quarterly:
            fallback = await _income_fallback(secucode)
            return fallback
        return {
            "annual": annual[:8],
            "quarterly": quarterly[:12],
            "currency": currency,
            "source": "eastmoney_f10",
            "fallback": False,
        }

    return await cache.get(key, 24 * 3600, factory)


async def _news_search(term: str, limit: int) -> list[dict[str, Any]]:
    param = {
        "uid": "",
        "keyword": term,
        "type": ["cmsArticleWebOld"],
        "client": "web",
        "clientType": "web",
        "clientVersion": "curr",
        "param": {
            "cmsArticleWebOld": {
                "searchScope": "default",
                "sort": "default",
                "pageIndex": 1,
                "pageSize": max(limit * 2, 20),
                "preTag": "<em>",
                "postTag": "</em>",
            }
        },
    }
    payload = await http.get_json(
        NEWS_SEARCH,
        params={"cb": "cb", "param": json.dumps(param, ensure_ascii=False, separators=(",", ":"))},
        headers=EASTMONEY_HEADERS,
        jsonp=True,
    )
    rows = (
        ((payload or {}).get("result") or {}).get("cmsArticleWebOld") or []
        if isinstance(payload, dict)
        else []
    )
    results = []
    seen: set[str] = set()
    for row in rows:
        url = str(row.get("url") or "")
        title = _clean_text(row.get("title"))
        if not title or not url or url in seen:
            continue
        seen.add(url)
        results.append(
            {
                "title": title,
                "summary": _clean_text(row.get("content"))[:220],
                "date": str(row.get("date") or ""),
                "media": _clean_text(row.get("mediaName")) or "东方财富",
                "url": url,
            }
        )
    results.sort(key=lambda item: item["date"], reverse=True)
    return results


async def stock_news(symbol: str, keyword: str | None = None, limit: int = 12) -> list[dict[str, Any]]:
    info = await resolve(symbol)
    search_keyword = keyword or info["name"] or info["symbol"]
    key = f"stock-news:v4:{info['symbol']}:{search_keyword}:{limit}"

    async def factory() -> list[dict[str, Any]]:
        results = await _news_search(search_keyword, limit)
        if len(results) < limit and search_keyword != info["symbol"]:
            try:
                extra = await _news_search(info["symbol"], limit)
                known = {item["url"] for item in results}
                results.extend(item for item in extra if item["url"] not in known)
            except Exception:
                pass
        return results[:limit]

    return await cache.get(key, 600, factory)


async def fast_news(limit: int = 24) -> list[dict[str, Any]]:
    async def factory() -> list[dict[str, Any]]:
        payload = await http.get_json(
            FAST_NEWS,
            params={
                "client": "web",
                "biz": "web_724",
                "fastColumn": 102,
                "sortEnd": "",
                "pageSize": max(limit, 30),
                "req_trace": str(int(time.time() * 1000)),
            },
            headers=EASTMONEY_HEADERS,
        )
        data = (payload or {}).get("data") if isinstance(payload, dict) else None
        rows = (data or {}).get("fastNewsList") or []
        results = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            summary = _clean_text(row.get("summary") or row.get("content") or "")
            title = _clean_text(row.get("title") or "")
            if not title:
                match = re.match(r"^【([^】]+)】", summary)
                title = match.group(1) if match else summary[:72]
            url = str(row.get("url") or row.get("url_w") or row.get("wapUrl") or "")
            if not title:
                continue
            results.append(
                {
                    "title": title,
                    "summary": summary[:240],
                    "date": str(row.get("showTime") or row.get("date") or row.get("time") or ""),
                    "media": _clean_text(row.get("mediaName")) or "东方财富 7×24",
                    "url": url,
                    "important": bool(row.get("important") or row.get("isImportant")),
                }
            )
        return results[:limit]

    return await cache.get(f"fast-news:v3:{limit}", 120, factory)


def market_status() -> dict[str, Any]:
    now = datetime.now(ET)
    day_key = now.date().isoformat()
    weekday = now.weekday() < 5
    trading_day = weekday and day_key not in MARKET_HOLIDAYS_2026
    minutes = now.hour * 60 + now.minute
    if trading_day and 9 * 60 + 30 <= minutes < 16 * 60:
        state, label = "open", "盘中"
    elif trading_day and 4 * 60 <= minutes < 9 * 60 + 30:
        state, label = "pre", "盘前"
    elif trading_day and 16 * 60 <= minutes < 20 * 60:
        state, label = "after", "盘后"
    else:
        state, label = "closed", "休市"

    next_open = None
    if trading_day and minutes < 9 * 60 + 30:
        next_open = datetime.combine(now.date(), dtime(9, 30), tzinfo=ET)
    else:
        for offset in range(1, 15):
            candidate = now.date() + timedelta(days=offset)
            if candidate.weekday() < 5 and candidate.isoformat() not in MARKET_HOLIDAYS_2026:
                next_open = datetime.combine(candidate, dtime(9, 30), tzinfo=ET)
                break

    return {
        "state": state,
        "label": label,
        "et": now.isoformat(timespec="seconds"),
        "et_time": now.strftime("%H:%M"),
        "et_date": now.strftime("%Y-%m-%d"),
        "trading_day": trading_day,
        "next_open": next_open.isoformat(timespec="seconds") if next_open else None,
    }


def strip_html(value: Any) -> str:
    return _clean_text(value)
