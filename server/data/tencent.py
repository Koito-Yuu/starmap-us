from __future__ import annotations

import logging
from typing import Any

from server.config import BROWSER_UA, CACHE_DIR
from server.data.cache import JsonCache
from server.data.http import UpstreamError, http

logger = logging.getLogger(__name__)
cache = JsonCache(CACHE_DIR)
BASE = "https://qt.gtimg.cn/q="
HEADERS = {"User-Agent": BROWSER_UA, "Referer": "https://gu.qq.com/"}

INDEX_CODES = {"SPX": "usINX", "COMP": "usIXIC", "DJIA": "usDJI", "IWM": "usIWM"}
EXCHANGES = {"OQ": "NASDAQ", "N": "NYSE", "AM": "AMEX", "PS": "PINK", "PK": "PINK"}


def _num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    text = str(value).replace("%", "").replace(",", "").strip()
    if not text or text in {"--", "N/A", "-"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _is_etf(name: str) -> bool:
    upper = (name or "").upper()
    return "ETF" in upper or "ETP" in upper


def _normalize(fields: list[str], symbol: str, name_override: str | None = None) -> dict[str, Any] | None:
    price = _num(fields[3]) if len(fields) > 3 else None
    if price is None or price <= 0:
        return None
    code = fields[2] if len(fields) > 2 else ""
    suffix = code.rsplit(".", 1)[-1].upper() if "." in code else ""
    name = name_override or (fields[1] if len(fields) > 1 else symbol)
    mcap_raw = _num(fields[44]) if len(fields) > 44 else None
    return {
        "symbol": symbol,
        "em_symbol": symbol,
        "name": name,
        "market": 0,
        "exchange": EXCHANGES.get(suffix, "US"),
        "currency": fields[35] if len(fields) > 35 else "USD",
        "price": price,
        "open": _num(fields[5]) if len(fields) > 5 else None,
        "high": _num(fields[33]) if len(fields) > 33 else None,
        "low": _num(fields[34]) if len(fields) > 34 else None,
        "prev_close": _num(fields[4]) if len(fields) > 4 else None,
        "change": _num(fields[31]) if len(fields) > 31 else None,
        "change_pct": _num(fields[32]) if len(fields) > 32 else None,
        "volume": _num(fields[36]) if len(fields) > 36 else None,
        "amount": _num(fields[37]) if len(fields) > 37 else None,
        "pe": _num(fields[39]) if len(fields) > 39 else None,
        "pb": _num(fields[51]) if len(fields) > 51 else None,
        "dividend_yield": _num(fields[52]) if len(fields) > 52 else None,
        "market_cap": mcap_raw * 1e8 if mcap_raw and mcap_raw > 0 else None,
        "week52_high": _num(fields[48]) if len(fields) > 48 else None,
        "week52_low": _num(fields[49]) if len(fields) > 49 else None,
        "eps_ttm": None,
        "is_etf": _is_etf(name),
        "updated_at": fields[30] if len(fields) > 30 else None,
        "source": "tencent",
    }


async def _fetch(codes: list[str]) -> list[tuple[str, list[str]]]:
    text = (await http.get_bytes(BASE + ",".join(codes), headers=HEADERS)).decode(
        "gbk", errors="replace"
    )
    parsed: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        if '="' not in line:
            continue
        key, payload = line.split('="', 1)
        fields = payload.rsplit('";', 1)[0].split("~")
        parsed.append((key.strip().removeprefix("v_"), fields))
    return parsed


async def quotes(symbols: list[str]) -> list[dict[str, Any]]:
    wanted = [item.strip().upper() for item in symbols if item.strip()][:50]
    if not wanted:
        return []
    key = "tencent:quotes:" + ",".join(sorted(wanted))

    async def factory() -> list[dict[str, Any]]:
        parsed = await _fetch([f"us{item}" for item in wanted])
        by_code = {code.lower(): fields for code, fields in parsed}
        results = []
        for symbol in wanted:
            fields = by_code.get(f"us{symbol}".lower())
            if not fields:
                continue
            item = _normalize(fields, symbol)
            if item:
                results.append(item)
        if not results:
            raise UpstreamError("tencent quotes unavailable")
        return results

    return await cache.get(key, 15, factory, persist=False)


async def quote(symbol: str) -> dict[str, Any]:
    symbol = symbol.strip().upper()
    items = await quotes([symbol])
    if not items:
        raise UpstreamError(f"tencent quote unavailable for {symbol}")
    return items[0]


async def index_quotes() -> list[dict[str, Any]]:
    key = "tencent:indices"

    async def factory() -> list[dict[str, Any]]:
        parsed = await _fetch(list(INDEX_CODES.values()))
        by_code = {code.lower(): fields for code, fields in parsed}
        results = []
        for symbol, code in INDEX_CODES.items():
            fields = by_code.get(code.lower())
            if not fields:
                continue
            item = _normalize(fields, symbol)
            if item:
                item.update({"market": 0, "kind": "index", "source": "tencent"})
                results.append(item)
        if not results:
            raise UpstreamError("tencent index quotes unavailable")
        return results

    return await cache.get(key, 20, factory)
