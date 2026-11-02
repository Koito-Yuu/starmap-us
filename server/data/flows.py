"""资金流、空头兴趣与期权隐含视角的补充数据源。

全部为免密钥公开接口：Eastmoney push2his 资金流日 K、Nasdaq 空头兴趣、
Cboe 延迟期权链（1.8 MB 全链在服务端聚合后再下发）。
"""

from __future__ import annotations

import logging
import math
import re
from collections import defaultdict
from datetime import datetime
from typing import Any

from server.config import CACHE_DIR, EASTMONEY_HEADERS, NASDAQ_HEADERS
from server.data.cache import JsonCache
from server.data.eastmoney import PUSH2HIS, resolve
from server.data.http import UpstreamError, http

logger = logging.getLogger(__name__)
cache = JsonCache(CACHE_DIR)

FFLOW_FIELDS = "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63"
OPTION_RE = re.compile(r"^([A-Z.]{1,6}?)(\d{6})([CP])(\d{8})$")


def _num(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).replace("$", "").replace(",", "").replace("%", "").strip()
    if not text or text in {"--", "N/A", "-", "undefined"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _round(value: Any, digits: int = 2) -> float | None:
    number = _num(value)
    return round(number, digits) if number is not None else None


def _cumulative(values: list[float | None], window: int) -> float | None:
    tail = [item for item in values[-window:] if item is not None]
    if len(tail) < min(window, 3):
        return None
    return round(sum(tail), 2)


async def capital_flow(symbol: str, limit: int = 90) -> dict[str, Any]:
    """主力/大单/中单/小单日度净流入，以及多窗口累计与价量背离。"""

    info = await resolve(symbol)
    secid = info["secid"]
    key = f"flow:v1:{secid}"

    async def factory() -> dict[str, Any]:
        payload = await http.get_json(
            f"{PUSH2HIS}/stock/fflow/daykline/get",
            params={
                "lmt": 0,
                "klt": 101,
                "secid": secid,
                "fields1": "f1,f2,f3,f7",
                "fields2": FFLOW_FIELDS,
                "ut": "b2884a393a59ad64002292a3e90d46a5",
            },
            headers=EASTMONEY_HEADERS,
        )
        rows = ((payload or {}).get("data") or {}).get("klines") or []
        dates: list[str] = []
        main: list[float | None] = []
        superlarge: list[float | None] = []
        large: list[float | None] = []
        mid: list[float | None] = []
        small: list[float | None] = []
        close: list[float | None] = []
        pct: list[float | None] = []
        for row in rows:
            parts = str(row).split(",")
            if len(parts) < 13:
                continue
            dates.append(parts[0])
            main.append(_num(parts[1]))
            small.append(_num(parts[2]))
            mid.append(_num(parts[3]))
            large.append(_num(parts[4]))
            superlarge.append(_num(parts[5]))
            close.append(_num(parts[11]))
            pct.append(_num(parts[12]))
        if not dates:
            raise UpstreamError("empty flow kline")

        # 连续净流入天数：以主力口径统计最近同向的天数
        streak = 0
        for value in reversed(main):
            if value is None:
                break
            if streak == 0:
                streak = 1 if value >= 0 else -1
            elif (value >= 0) != (streak > 0):
                break
            else:
                streak += 1 if value >= 0 else -1

        window = list(zip(dates, main, pct))[-20:]
        both_up = sum(1 for _, m, p in window if m is not None and p is not None and m > 0 and p > 0)
        both_down = sum(1 for _, m, p in window if m is not None and p is not None and m < 0 and p < 0)
        return {
            "dates": dates[-limit:],
            "main": main[-limit:],
            "superlarge": superlarge[-limit:],
            "large": large[-limit:],
            "mid": mid[-limit:],
            "small": small[-limit:],
            "close": close[-limit:],
            "pct": pct[-limit:],
            "streak": streak,
            "cum5": _cumulative(main, 5),
            "cum10": _cumulative(main, 10),
            "cum20": _cumulative(main, 20),
            "cum60": _cumulative(main, 60),
            "resonance": round((both_up + both_down) / len(window) * 100, 1) if window else None,
        }

    return await cache.get(key, 6 * 3600, factory)


async def short_interest(symbol: str, *, float_shares: float | None = None) -> dict[str, Any]:
    """Nasdaq 结算口径空头兴趣序列；调用方传入流通股本以折算空头占比。"""

    query = symbol.strip().upper()
    key = f"short:v1:{query}"

    async def factory() -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        for assetclass in ("stocks", "etf"):
            payload = await http.get_json(
                f"https://api.nasdaq.com/api/quote/{query}/short-interest",
                params={"assetclass": assetclass},
                headers=NASDAQ_HEADERS,
                optional=True,
            )
            table = ((payload or {}).get("data") or {}).get("shortInterestTable") or {}
            rows = table.get("rows") or []
            if rows:
                break
        if not rows:
            raise UpstreamError("no short interest data")

        history = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                settle = datetime.strptime(str(row.get("settlementDate")), "%m/%d/%Y").strftime("%Y-%m-%d")
            except ValueError:
                continue
            history.append(
                {
                    "date": settle,
                    "interest": _num(row.get("interest")),
                    "avg_volume": _num(row.get("avgDailyShareVolume")),
                    "days_to_cover": _round(row.get("daysToCover"), 2),
                }
            )
        history.sort(key=lambda item: item["date"])
        latest = history[-1]
        prior = history[-2] if len(history) > 1 else None
        interest = latest.get("interest")
        change_pct = None
        if prior and interest and prior.get("interest"):
            change_pct = round((interest - prior["interest"]) / prior["interest"] * 100, 2)
        return {
            "latest": latest,
            "prior_date": prior["date"] if prior else None,
            "change_pct": change_pct,
            "history": history[-26:],
        }

    result = await cache.get(key, 12 * 3600, factory)
    interest = (result.get("latest") or {}).get("interest")
    result["float_shares"] = float_shares
    result["short_pct_float"] = (
        round(interest / float_shares * 100, 2) if interest and float_shares else None
    )
    return result


def _parse_option(raw: str) -> tuple[str, int, float] | None:
    match = OPTION_RE.match(str(raw or "").strip().upper())
    if not match:
        return None
    _, expiry, kind, strike = match.groups()
    try:
        date = datetime.strptime(expiry, "%y%m%d").date()
    except ValueError:
        return None
    return date.strftime("%Y-%m-%d"), 1 if kind == "C" else 0, int(strike) / 1000


def _mid(contract: dict[str, Any]) -> float | None:
    if not contract:
        return None
    bid = _num(contract.get("bid"))
    ask = _num(contract.get("ask"))
    if bid and ask and bid > 0 and ask >= bid:
        return (bid + ask) / 2
    last = _num(contract.get("last_trade_price"))
    return last if last else None


def _nearest_strike(contracts: list[dict[str, Any]], spot: float) -> dict[str, Any]:
    return min(contracts, key=lambda item: abs(item["strike"] - spot), default={})


def _atm_iv(contracts: list[dict[str, Any]], spot: float) -> tuple[float | None, float | None]:
    """返回 (平值隐含波动率, 平值行权价)。用 IV 场内插值，避免单点噪声。"""
    buckets: dict[float, list[float]] = defaultdict(list)
    for contract in contracts:
        strike = contract["strike"]
        iv = _num(contract.get("iv"))
        if iv and 0.01 < iv < 3:
            buckets[strike].append(iv)
    points = sorted(
        (strike, sum(values) / len(values)) for strike, values in buckets.items()
    )
    if not points:
        return None, None
    strikes = [item[0] for item in points]
    nearest = min(range(len(strikes)), key=lambda index: abs(strikes[index] - spot))
    if len(points) == 1:
        return points[0][1], points[0][0]
    left = max(nearest - 1, 0)
    right = min(nearest + 1, len(points) - 1)
    if left == right:
        return points[left][1], points[left][0]
    span = strikes[right] - strikes[left]
    weight = 0.5 if span <= 0 else (spot - strikes[left]) / span
    iv = points[left][1] * (1 - weight) + points[right][1] * weight
    return iv, strikes[nearest]


def _skew(contracts: list[dict[str, Any]], target: float = 0.25) -> tuple[float | None, float | None]:
    """返回 (25Δ 看跌 IV, 25Δ 看涨 IV)，正差值即常见的认沽偏度。"""
    picks: dict[int, tuple[float, float]] = {}
    for contract in contracts:
        delta = _num(contract.get("delta"))
        iv = _num(contract.get("iv"))
        if delta is None or not iv:
            continue
        distance = abs(abs(delta) - target)
        kind = contract["kind"]
        if abs(delta) <= 0.02 or abs(delta) > 0.6 or distance >= 0.12:
            continue
        if kind not in picks or distance < picks[kind][0]:
            picks[kind] = (distance, iv)
    return picks.get(0, (None, None))[1], picks.get(1, (None, None))[1]


def _max_pain(strikes: list[float], call_oi: dict[float, float], put_oi: dict[float, float]) -> float | None:
    if not strikes:
        return None
    best: tuple[float, float] | None = None
    for candidate in strikes:
        pain = 0.0
        for strike in strikes:
            if candidate > strike:
                pain += call_oi.get(strike, 0) * (candidate - strike)
            elif candidate < strike:
                pain += put_oi.get(strike, 0) * (strike - candidate)
        if best is None or pain < best[0]:
            best = (pain, candidate)
    return best[1] if best else None


async def options_snapshot(symbol: str) -> dict[str, Any]:
    """Cboe 延迟期权链 → 期望波动、偏度、PCR、最大痛点与 IV 期限结构。"""

    query = symbol.strip().upper()
    key = f"options:v1:{query}"

    async def factory() -> dict[str, Any]:
        payload = await http.get_json(
            f"https://cdn.cboe.com/api/global/delayed_quotes/options/{query}.json",
            headers={**EASTMONEY_HEADERS, "Referer": "https://www.cboe.com/"},
            timeout=30.0,
            retries=1,
        )
        data = (payload or {}).get("data") or {}
        raw_rows = data.get("options") or []
        spot = _num(data.get("current_price")) or _num(data.get("close"))
        if not raw_rows or not spot or spot <= 0:
            raise UpstreamError("no option chain")

        contracts: list[dict[str, Any]] = []
        for row in raw_rows:
            if not isinstance(row, dict):
                continue
            parsed = _parse_option(row.get("option"))
            if not parsed:
                continue
            expiry, kind, strike = parsed
            contracts.append(
                {
                    "expiry": expiry,
                    "kind": kind,
                    "strike": strike,
                    "iv": row.get("iv"),
                    "delta": row.get("delta"),
                    "oi": _num(row.get("open_interest")) or 0,
                    "volume": _num(row.get("volume")) or 0,
                    "bid": row.get("bid"),
                    "ask": row.get("ask"),
                    "last_trade_price": row.get("last_trade_price"),
                }
            )
        if not contracts:
            raise UpstreamError("option chain unparsable")

        today = min(contract["expiry"] for contract in contracts)
        by_expiry: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for contract in contracts:
            by_expiry[contract["expiry"]].append(contract)
        expiries = sorted(by_expiry)

        def dte(expiry: str) -> float:
            days = (datetime.strptime(expiry, "%Y-%m-%d").date() - datetime.strptime(today, "%Y-%m-%d").date()).days
            return max(days, 0)

        # 期望波动取 21~70 天中最接近 30 天的到期日，样本更稳定
        reference = min(expiries, key=lambda item: (abs(dte(item) - 30), dte(item)))
        reference_rows = by_expiry[reference]
        atm_iv, atm_strike = _atm_iv(reference_rows, spot)
        call_mid = _mid(_nearest_strike([item for item in reference_rows if item["kind"] == 1], spot))
        put_mid = _mid(_nearest_strike([item for item in reference_rows if item["kind"] == 0], spot))
        straddle = (call_mid or 0) + (put_mid or 0)
        year = max(dte(reference), 1) / 365
        implied_move = spot * atm_iv * math.sqrt(year) if atm_iv else None
        skew_put, skew_call = _skew(reference_rows)

        call_oi: dict[float, float] = defaultdict(float)
        put_oi: dict[float, float] = defaultdict(float)
        total_call_oi = total_put_oi = total_call_vol = total_put_vol = 0.0
        for contract in contracts:
            if contract["kind"] == 1:
                call_oi[contract["strike"]] += contract["oi"]
                total_call_oi += contract["oi"]
                total_call_vol += contract["volume"]
            else:
                put_oi[contract["strike"]] += contract["oi"]
                total_put_oi += contract["oi"]
                total_put_vol += contract["volume"]

        term = []
        for expiry in expiries[:8]:
            iv, _ = _atm_iv(by_expiry[expiry], spot)
            if iv:
                term.append(
                    {
                        "expiry": expiry,
                        "dte": int(dte(expiry)),
                        "iv": round(iv * 100, 1),
                        "oi": round(sum(item["oi"] for item in by_expiry[expiry])),
                    }
                )

        return {
            "symbol": query,
            "spot": spot,
            "as_of": str(payload.get("timestamp") or ""),
            "iv30": _round(data.get("iv30"), 1),
            "iv30_change": _round(data.get("iv30_change"), 1),
            "expiry": reference,
            "dte": int(dte(reference)),
            "atm_strike": atm_strike,
            "atm_iv": round(atm_iv * 100, 1) if atm_iv else None,
            "expected_move": round(implied_move, 2) if implied_move else None,
            "expected_move_pct": round(implied_move / spot * 100, 2) if implied_move else None,
            "straddle": round(straddle, 2) if straddle else None,
            "straddle_pct": round(straddle / spot * 100, 2) if straddle else None,
            "skew_put_iv": round(skew_put * 100, 1) if skew_put else None,
            "skew_call_iv": round(skew_call * 100, 1) if skew_call else None,
            "skew": round((skew_put - skew_call) * 100, 1) if skew_put and skew_call else None,
            "put_call_oi": round(total_put_oi / total_call_oi, 2) if total_call_oi else None,
            "put_call_volume": round(total_put_vol / total_call_vol, 2) if total_call_vol else None,
            "max_pain": _max_pain(sorted(set(call_oi) | set(put_oi)), call_oi, put_oi),
            "expiries": [
                {"expiry": expiry, "dte": int(dte(expiry)), "contracts": len(by_expiry[expiry])}
                for expiry in expiries[:10]
            ],
            "term": term,
            "total_contracts": len(contracts),
        }

    return await cache.get(key, 30 * 60, factory)
