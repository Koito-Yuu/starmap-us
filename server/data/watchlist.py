"""自选研究页的聚合分析。

这里只负责把已有数据源（东方财富日线/报价/全市场快照、Nasdaq SPY 基准）
整理成一个自包含的只读快照。等权指数是由归一收盘价求均值得到的监控指标，
不是可交易组合，也不做任何再平衡或成本假设。
"""

from __future__ import annotations

import asyncio
import logging
import math
import numbers
import re
import statistics
import time
from datetime import datetime
from typing import Any, Iterable, Sequence
from zoneinfo import ZoneInfo

from server.data import analysis, eastmoney, nasdaq

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

RANGE_TRADING_DAYS = {"3M": 63, "6M": 126, "1Y": 252}
DEFAULT_RANGE = "3M"
MAX_SYMBOLS = 20
MIN_COMMON_DAYS = 5
MAX_PERFORMANCE_POINTS = 600
CANDLE_TIMEFRAME = "1Y"
BENCHMARK_SYMBOL = "SPY"
BENCHMARK_DAYS = 420
MAX_CONCURRENCY = 5
ANALYZE_CACHE_TTL = 30.0
RETURN_WINDOWS = {
    "return_1w": 5,
    "return_1m": 21,
    "return_3m": 63,
    "return_6m": 126,
    "return_1y": 252,
}
_SYMBOL_RE = re.compile(r"[A-Z0-9][A-Z0-9._-]{0,15}")
_TONES = {"positive", "caution", "neutral"}
_ANALYZE_CACHE: dict[tuple[tuple[str, ...], str], tuple[float, dict[str, Any]]] = {}


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _round(value: Any, digits: int = 2) -> float | None:
    number = _finite(value)
    return round(number, digits) if number is not None else None


def _text(value: Any) -> str:
    return str(value or "").strip()


def normalize_range(raw: Any) -> str:
    if raw is None:
        return DEFAULT_RANGE
    value = str(raw).strip().upper()
    if value not in RANGE_TRADING_DAYS:
        raise ValueError("range 仅支持 3M / 6M / 1Y")
    return value


def parse_symbols(raw: str | Sequence[str] | None) -> list[str]:
    if raw is None:
        raise ValueError("symbols 不能为空")
    if isinstance(raw, str):
        parts = [item.strip().upper() for item in raw.split(",")]
    else:
        parts = [str(item).strip().upper() for item in raw]
    symbols = list(dict.fromkeys(item for item in parts if item))
    if not symbols:
        raise ValueError("symbols 不能为空")
    if len(symbols) > MAX_SYMBOLS:
        raise ValueError(f"symbols 最多支持 {MAX_SYMBOLS} 个")
    invalid = [item for item in symbols if not _SYMBOL_RE.fullmatch(item)]
    if invalid:
        raise ValueError(f"非法代码：{', '.join(invalid[:3])}")
    return symbols


def _clean_bars(bars: Iterable[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """按日期排序、去重，并丢弃没有有效收盘价的 bar。"""
    indexed: dict[str, dict[str, Any]] = {}
    for bar in bars or []:
        if not isinstance(bar, dict):
            continue
        date_value = _text(bar.get("t"))[:10]
        close = _finite(bar.get("c"))
        if not date_value or close is None or close <= 0:
            continue
        row = dict(bar)
        row["t"] = date_value
        row["c"] = close
        for key in ("o", "h", "l", "v", "a"):
            row[key] = _finite(bar.get(key))
        row["chg"] = _finite(bar.get("chg"))
        indexed[date_value] = row
    return [indexed[key] for key in sorted(indexed)]


def _period_return(closes: list[float], days: int) -> float | None:
    if len(closes) <= days:
        return None
    base = closes[-days - 1]
    if base <= 0:
        return None
    return _round((closes[-1] / base - 1) * 100)


def _ytd_return(bars: list[dict[str, Any]]) -> float | None:
    if not bars:
        return None
    year = bars[-1]["t"][:4]
    prior = [bar for bar in bars if bar["t"][:4] < year]
    if prior:
        base = prior[-1]["c"]
    else:
        same_year = [bar for bar in bars if bar["t"][:4] == year]
        if not same_year:
            return None
        base = same_year[0]["c"]
    if base <= 0:
        return None
    return _round((bars[-1]["c"] / base - 1) * 100)


def compute_returns(bars: list[dict[str, Any]]) -> dict[str, float | None]:
    closes = [bar["c"] for bar in bars]
    result = {key: _period_return(closes, days) for key, days in RETURN_WINDOWS.items()}
    result["ytd"] = _ytd_return(bars)
    return result


def _atr_pct(bars: list[dict[str, Any]], period: int = 14) -> float | None:
    if len(bars) < period + 1:
        return None
    true_ranges: list[float] = []
    for previous, current in zip(bars, bars[1:]):
        close = current["c"]
        high = _finite(current.get("h"))
        low = _finite(current.get("l"))
        high = close if high is None else high
        low = close if low is None else low
        previous_close = previous["c"]
        true_ranges.append(
            max(high - low, abs(high - previous_close), abs(low - previous_close))
        )
    if len(true_ranges) < period:
        return None
    atr = sum(true_ranges[-period:]) / period
    return _round(atr / bars[-1]["c"] * 100)


def _volume_ratio_20(bars: list[dict[str, Any]], period: int = 20) -> float | None:
    """最新成交量 / 之前 20 个交易日的平均成交量；缺量或含空值时不计算。"""
    if len(bars) < period + 1:
        return None
    window = bars[-period - 1:]
    latest = _finite(window[-1].get("v"))
    history = [_finite(bar.get("v")) for bar in window[:-1]]
    if latest is None or latest < 0 or any(value is None for value in history):
        return None
    average = sum(history) / period  # type: ignore[arg-type]
    if average <= 0:
        return None
    return _round(latest / average, 2)


def _max_drawdown(closes: list[float], window: int = 252) -> float | None:
    values = closes[-window:]
    if len(values) < 2:
        return None
    peak = values[0]
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        worst = min(worst, value / peak - 1)
    return _round(worst * 100)


def _window_stats(closes: list[float], window: int = 252) -> dict[str, float | None]:
    values = closes[-window:]
    high = max(values)
    low = min(values)
    last = values[-1]
    return {
        "week52_high": _round(high, 4),
        "week52_low": _round(low, 4),
        "from_high_52w": _round((last / high - 1) * 100) if high > 0 else None,
        "range_position_52w": _round((last - low) / (high - low) * 100, 1) if high > low else None,
    }


def _corr(left: list[float], right: list[float]) -> float | None:
    if len(left) < 3 or len(left) != len(right):
        return None
    mean_left = sum(left) / len(left)
    mean_right = sum(right) / len(right)
    covariance = sum(
        (a - mean_left) * (b - mean_right) for a, b in zip(left, right)
    )
    variance_left = sum((a - mean_left) ** 2 for a in left)
    variance_right = sum((b - mean_right) ** 2 for b in right)
    if variance_left <= 0 or variance_right <= 0:
        return None
    return _round(covariance / math.sqrt(variance_left * variance_right), 3)


def _beta_correlation(
    bars: list[dict[str, Any]],
    benchmark_bars: list[dict[str, Any]] | None,
) -> tuple[float | None, float | None]:
    if not bars or not benchmark_bars:
        return None, None
    benchmark = {bar["t"]: bar["c"] for bar in _clean_bars(benchmark_bars)}
    own = bars[-252:]
    asset_returns: list[float] = []
    bench_returns: list[float] = []
    for previous, current in zip(own, own[1:]):
        bench_previous = benchmark.get(previous["t"])
        bench_current = benchmark.get(current["t"])
        if bench_previous is None or bench_current is None or bench_previous <= 0:
            continue
        asset_returns.append(current["c"] / previous["c"] - 1)
        bench_returns.append(bench_current / bench_previous - 1)
    if len(asset_returns) < 20:
        return None, None
    count = len(asset_returns)
    mean_asset = sum(asset_returns) / count
    mean_bench = sum(bench_returns) / count
    covariance = sum(
        (asset - mean_asset) * (bench - mean_bench)
        for asset, bench in zip(asset_returns, bench_returns)
    ) / (count - 1)
    variance_asset = sum((value - mean_asset) ** 2 for value in asset_returns) / (count - 1)
    variance_bench = sum((value - mean_bench) ** 2 for value in bench_returns) / (count - 1)
    beta = covariance / variance_bench if variance_bench > 0 else None
    correlation = (
        covariance / math.sqrt(variance_asset * variance_bench)
        if variance_asset > 0 and variance_bench > 0
        else None
    )
    return _round(beta), _round(correlation)


def build_signals(item: dict[str, Any]) -> list[dict[str, str]]:
    """只输出可读标签，不做评分、不推断仓位。"""
    signals: list[dict[str, str]] = []

    def add(code: str, label: str, tone: str) -> None:
        if tone in _TONES:
            signals.append({"code": code, "label": label, "tone": tone})

    rsi_value = _finite(item.get("rsi14"))
    if rsi_value is not None:
        if rsi_value >= 70:
            add("rsi_overbought", "RSI 超买", "caution")
        elif rsi_value <= 30:
            add("rsi_oversold", "RSI 超卖", "neutral")

    above_ma200 = item.get("above_ma200")
    if above_ma200 is True:
        add("above_ma200", "站上 200 日均线", "positive")
    elif above_ma200 is False:
        add("below_ma200", "跌破 200 日均线", "caution")

    from_high = _finite(item.get("from_high_52w"))
    if from_high is not None:
        if from_high >= -2:
            add("near_52w_high", "接近 52 周高点", "positive")
        elif from_high <= -20:
            add("deep_drawdown", "较高点回撤超 20%", "caution")

    volume_ratio = _finite(item.get("volume_ratio_20"))
    if volume_ratio is not None and volume_ratio >= 1.8:
        add("volume_surge", "成交量放大", "neutral")

    return_1m = _finite(item.get("return_1m"))
    if return_1m is not None:
        if return_1m >= 10:
            add("strong_1m", "近一月强势", "positive")
        elif return_1m <= -10:
            add("weak_1m", "近一月弱势", "caution")

    return signals


def build_item(
    symbol: str,
    payload: dict[str, Any],
    quote: dict[str, Any] | None = None,
    snapshot: dict[str, Any] | None = None,
    benchmark_bars: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    bars = _clean_bars(payload.get("bars"))
    if not bars:
        raise ValueError(f"{symbol} 没有可用日线")
    quote = quote or {}
    snapshot = snapshot or {}
    closes = [bar["c"] for bar in bars]
    last = closes[-1]

    risk: dict[str, Any] = {}
    if len(bars) >= 40:
        try:
            risk = analysis.risk_report(bars, benchmark_bars) or {}
        except Exception as exc:  # 单票指标异常不应影响整个自选页
            logger.info("watchlist risk report failed for %s: %s", symbol, exc)
    trend = risk.get("trend") or {}
    horizon = (risk.get("horizons") or {}).get("1Y") or {}

    def moving_average(period: int) -> float | None:
        value = _finite(trend.get(f"ma{period}"))
        if value is None:
            value = analysis.sma(closes, period)
        return _round(value)

    ma20 = moving_average(20)
    ma50 = moving_average(50)
    ma200 = moving_average(200)
    stats = _window_stats(closes)

    beta = _finite(horizon.get("beta"))
    correlation = _finite(horizon.get("correlation"))
    if beta is None or correlation is None:
        alt_beta, alt_correlation = _beta_correlation(bars, benchmark_bars)
        beta = beta if beta is not None else alt_beta
        correlation = correlation if correlation is not None else alt_correlation

    max_drawdown = _finite(horizon.get("max_drawdown"))
    if max_drawdown is None:
        max_drawdown = _max_drawdown(closes)

    price = _finite(quote.get("price"))
    if price is None or price <= 0:
        price = last
    change_pct = _finite(quote.get("change_pct"))
    if change_pct is None and len(closes) > 1:
        change_pct = _round((last / closes[-2] - 1) * 100)

    name = (
        _text(quote.get("name"))
        or _text(snapshot.get("name"))
        or _text(payload.get("name"))
        or symbol
    )
    industry = _text(snapshot.get("industry")) or _text(quote.get("industry"))
    if industry in {"", "-", "--", "N/A", "n/a"}:
        industry = "其他"
    pe = _finite(snapshot.get("pe"))
    if pe is None:
        pe = _finite(quote.get("pe"))
    pb = _finite(snapshot.get("pb"))
    if pb is None:
        pb = _finite(quote.get("pb"))
    market_cap = _finite(quote.get("market_cap"))
    if market_cap is None or market_cap <= 0:
        market_cap = _finite(snapshot.get("market_cap"))

    period_returns = compute_returns(bars)
    benchmark_return_3m = None
    if benchmark_bars:
        benchmark_closes = [bar["c"] for bar in _clean_bars(benchmark_bars)]
        benchmark_return_3m = _period_return(benchmark_closes, 63)
    relative_3m = (
        _round(period_returns["return_3m"] - benchmark_return_3m)
        if period_returns["return_3m"] is not None and benchmark_return_3m is not None
        else None
    )

    item: dict[str, Any] = {
        "symbol": symbol,
        "name": name,
        "price": _round(price, 4),
        "change_pct": _round(change_pct),
        "market_cap": market_cap,
        "pe": _round(pe),
        "pb": _round(pb),
        "industry": industry,
        "source": _text(payload.get("source")) or "eastmoney",
        "price_basis": _text(payload.get("price_basis")) or "raw",
        "as_of": bars[-1]["t"],
        **period_returns,
        "relative_3m": relative_3m,
        "rsi14": _round(analysis.rsi(closes, 14)),
        "ma20": ma20,
        "ma50": ma50,
        "ma200": ma200,
        "above_ma20": None if ma20 is None else bool(last >= ma20),
        "above_ma50": None if ma50 is None else bool(last >= ma50),
        "above_ma200": None if ma200 is None else bool(last >= ma200),
        "atr_pct": _atr_pct(bars),
        "from_high_52w": stats["from_high_52w"],
        "range_position_52w": stats["range_position_52w"],
        "week52_low": stats["week52_low"],
        "week52_high": stats["week52_high"],
        "beta": _round(beta),
        "correlation": _round(correlation),
        "max_drawdown_1y": _round(max_drawdown),
        "volume_ratio_20": _volume_ratio_20(bars),
        "spark": [_round(value, 2) for value in closes[-63:]],
    }
    item["signals"] = build_signals(item)
    return item


def _close_maps(bars_map: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, float]]:
    return {
        symbol: {bar["t"]: bar["c"] for bar in bars}
        for symbol, bars in bars_map.items()
    }


def _downsample(
    dates: list[str],
    series: list[list[float | None]],
    max_points: int = MAX_PERFORMANCE_POINTS,
) -> tuple[list[str], list[list[float | None]]]:
    length = len(dates)
    if length <= max_points:
        return list(dates), [list(values) for values in series]
    step = math.ceil(length / max_points)
    indices = list(range(0, length, step))
    if indices[-1] != length - 1:
        indices.append(length - 1)
    return (
        [dates[index] for index in indices],
        [[values[index] for index in indices] for values in series],
    )


def _benchmark_series(
    benchmark_bars: list[dict[str, Any]] | None,
    dates: list[str],
) -> list[float | None]:
    """SPY 按共同日期前向填充，并把第一个共同日归一到 100。"""
    rows = _clean_bars(benchmark_bars)
    if not rows or not dates:
        return []
    cursor = 0
    last_close: float | None = None
    aligned: list[float | None] = []
    for date_value in dates:
        while cursor < len(rows) and rows[cursor]["t"] <= date_value:
            last_close = rows[cursor]["c"]
            cursor += 1
        aligned.append(last_close)
    if aligned[0] is None:
        return []
    base = aligned[0]
    return [
        _round(value / base * 100) if value is not None else None for value in aligned
    ]


def build_correlation(
    symbols: list[str],
    close_maps: dict[str, dict[str, float]],
    dates: list[str],
) -> dict[str, Any]:
    count = len(symbols)
    if count == 0:
        return {"symbols": [], "matrix": []}
    if count == 1:
        return {"symbols": symbols, "matrix": [[1.0]]}
    matrix: list[list[float | None]] = []
    if len(dates) < 4:
        return {"symbols": symbols, "matrix": [[None] * count for _ in range(count)]}

    returns: dict[str, list[float]] = {}
    for symbol in symbols:
        mapping = close_maps[symbol]
        values: list[float] = []
        previous = mapping[dates[0]]
        for date_value in dates[1:]:
            current = mapping[date_value]
            values.append(current / previous - 1 if previous > 0 else 0.0)
            previous = current
        returns[symbol] = values

    for left_symbol in symbols:
        row: list[float | None] = []
        for right_symbol in symbols:
            row.append(_corr(returns[left_symbol], returns[right_symbol]))
        matrix.append(row)
    return {"symbols": symbols, "matrix": matrix}


def build_performance(
    bars_map: dict[str, list[dict[str, Any]]],
    benchmark_bars: list[dict[str, Any]] | None,
    range_key: str,
    max_points: int = MAX_PERFORMANCE_POINTS,
) -> dict[str, Any]:
    range_key = normalize_range(range_key)
    cleaned = {
        str(symbol): rows
        for symbol, rows in ((symbol, _clean_bars(bars)) for symbol, bars in bars_map.items())
        if rows
    }
    symbols = list(cleaned)
    warnings: list[str] = []
    empty_performance = {"dates": [], "equal_weight": [], "benchmark": []}
    if not symbols:
        return {
            "performance": empty_performance,
            "correlation": {"symbols": [], "matrix": []},
            "warnings": warnings,
        }

    date_sets = [{bar["t"] for bar in rows} for rows in cleaned.values()]
    common = sorted(set.intersection(*date_sets)) if len(date_sets) > 1 else sorted(date_sets[0])
    if len(common) < MIN_COMMON_DAYS:
        warnings.append(
            f"所有标的的共同交易日不足 {MIN_COMMON_DAYS} 天，等权指数暂不可用。"
        )
        correlation = (
            {"symbols": symbols, "matrix": [[1.0]]}
            if len(symbols) == 1
            else {"symbols": symbols, "matrix": [[None] * len(symbols) for _ in symbols]}
        )
        return {
            "performance": empty_performance,
            "correlation": correlation,
            "warnings": warnings,
        }

    first_dates = {symbol: rows[0]["t"] for symbol, rows in cleaned.items()}
    earliest = min(first_dates.values())
    if common[0] > earliest:
        latest_first = max(first_dates.values())
        limiting = [symbol for symbol, value in first_dates.items() if value == latest_first]
        names = "、".join(limiting[:3])
        if len(limiting) > 3:
            names += " 等"
        warnings.append(
            f"等权指数按共同交易日计算，共同起点 {common[0]}"
            f"（受 {names or '个别标的'} 较短历史影响）。"
        )

    target = RANGE_TRADING_DAYS[range_key]
    window = common[-target:]
    if len(window) < target:
        warnings.append(
            f"共同区间仅有 {len(window)} 个交易日，短于 {range_key} 窗口，等权指数按现有区间展示。"
        )

    close_maps = _close_maps(cleaned)
    base_date = window[0]
    bases = {symbol: close_maps[symbol][base_date] for symbol in symbols}
    equal_weight = [
        _round(
            sum(close_maps[symbol][date_value] / bases[symbol] for symbol in symbols)
            / len(symbols)
            * 100
        )
        for date_value in window
    ]

    benchmark = _benchmark_series(benchmark_bars, window)
    if benchmark_bars and not benchmark:
        warnings.append("SPY 基准未覆盖共同区间，基准曲线暂不可用。")

    correlation = build_correlation(symbols, close_maps, common)
    if benchmark and len(benchmark) == len(equal_weight):
        dates, downsampled = _downsample(
            window, [equal_weight, benchmark], max_points=max_points
        )
        performance = {
            "dates": dates,
            "equal_weight": downsampled[0],
            "benchmark": downsampled[1],
        }
    else:
        dates, downsampled = _downsample(window, [equal_weight], max_points=max_points)
        performance = {
            "dates": dates,
            "equal_weight": downsampled[0],
            "benchmark": [],
        }

    return {
        "performance": performance,
        "correlation": correlation,
        "warnings": warnings,
    }


def build_sectors(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    total = len(items)
    if total == 0:
        return []
    groups: dict[str, dict[str, Any]] = {}
    for item in items:
        name = _text(item.get("industry")) or "其他"
        group = groups.setdefault(name, {"count": 0, "changes": []})
        group["count"] += 1
        change = _finite(item.get("change_pct"))
        if change is not None:
            group["changes"].append(change)
    rows = [
        {
            "name": name,
            "count": group["count"],
            "weight": _round(group["count"] / total * 100, 1),
            "avg_change_pct": (
                _round(sum(group["changes"]) / len(group["changes"]))
                if group["changes"]
                else None
            ),
        }
        for name, group in groups.items()
    ]
    rows.sort(key=lambda row: (-(row["weight"] or 0), row["name"]))
    return rows


def _average_correlation(correlation: dict[str, Any]) -> float | None:
    matrix = correlation.get("matrix") or []
    count = len(matrix)
    if count == 0:
        return None
    if count == 1:
        return _round(matrix[0][0]) if matrix and matrix[0] else None
    values = [
        _finite(matrix[row][column])
        for row in range(count)
        for column in range(row + 1, count)
    ]
    clean = [value for value in values if value is not None]
    return _round(sum(clean) / len(clean)) if clean else None


def build_summary(
    items: list[dict[str, Any]],
    performance: dict[str, Any],
    correlation: dict[str, Any],
) -> dict[str, Any]:
    changes = [value for value in (_finite(item.get("change_pct")) for item in items) if value is not None]
    one_month = [
        value for value in (_finite(item.get("return_1m")) for item in items) if value is not None
    ]

    def breadth(key: str) -> float | None:
        values = [
            item.get(key)
            for item in items
            if isinstance(item.get(key), bool)
        ]
        if not values:
            return None
        return _round(sum(1 for value in values if value) / len(values) * 100, 1)

    equal_weight = performance.get("equal_weight") or []
    equal_weight_return = (
        _round(float(equal_weight[-1]) - 100) if equal_weight and _finite(equal_weight[-1]) is not None else None
    )
    dispersion = _round(statistics.pstdev(one_month), 2) if len(one_month) >= 2 else None
    return {
        "count": len(items),
        "advancers": sum(1 for value in changes if value > 0),
        "decliners": sum(1 for value in changes if value < 0),
        "avg_change_pct": _round(sum(changes) / len(changes)) if changes else None,
        "median_return_1m": _round(statistics.median(one_month)) if one_month else None,
        "equal_weight_return": equal_weight_return,
        "breadth_above_ma20": breadth("above_ma20"),
        "breadth_above_ma50": breadth("above_ma50"),
        "breadth_above_ma200": breadth("above_ma200"),
        "dispersion": dispersion,
        "avg_correlation": _average_correlation(correlation),
    }


def _build_payload(
    tickers: list[str],
    payload_map: dict[str, dict[str, Any]],
    quote_map: dict[str, dict[str, Any]],
    universe_items: list[dict[str, Any]],
    benchmark_bars: list[dict[str, Any]] | None,
    range_key: str,
) -> dict[str, Any]:
    snapshots: dict[str, dict[str, Any]] = {}
    for item in universe_items:
        if not isinstance(item, dict):
            continue
        symbol = _text(item.get("symbol")).upper()
        if symbol:
            snapshots.setdefault(symbol, item)

    errors: list[str] = []
    warnings: list[str] = []
    items: list[dict[str, Any]] = []
    sources: dict[str, str | None] = {}
    bars_map: dict[str, list[dict[str, Any]]] = {}
    raw_symbols: list[str] = []

    for symbol in tickers:
        payload = payload_map.get(symbol)
        if not isinstance(payload, dict) or not payload:
            errors.append(f"{symbol} 历史行情获取失败")
            continue
        bars = _clean_bars(payload.get("bars"))
        if not bars:
            errors.append(f"{symbol} 历史行情不足")
            continue
        quote = quote_map.get(symbol)
        if quote is None:
            errors.append(f"{symbol} 实时报价获取失败")
        try:
            item = build_item(
                symbol,
                payload,
                quote,
                snapshots.get(symbol),
                benchmark_bars,
            )
        except Exception as exc:
            logger.info("watchlist item failed for %s: %s", symbol, exc)
            errors.append(f"{symbol} 指标计算失败")
            continue
        items.append(item)
        bars_map[symbol] = bars
        sources[symbol] = item.get("source")
        if item.get("source") == "nasdaq" or item.get("price_basis") == "raw":
            raw_symbols.append(symbol)

    if raw_symbols:
        warnings.append(
            f"{len(raw_symbols)} 只自选使用 Nasdaq 原始收盘价（未复权），"
            "区间收益与等权指数可能受除权跳空影响，明细中标注各标的来源。"
        )

    performance_bundle = build_performance(bars_map, benchmark_bars, range_key)
    warnings.extend(performance_bundle["warnings"])
    performance = performance_bundle["performance"]
    correlation = performance_bundle["correlation"]
    summary = build_summary(items, performance, correlation)

    return {
        "symbols": [{"symbol": item["symbol"], "name": item["name"]} for item in items],
        "as_of": datetime.now(ET).isoformat(timespec="seconds"),
        "range": range_key,
        "benchmark": BENCHMARK_SYMBOL,
        "sources": sources,
        "errors": list(dict.fromkeys(errors)),
        "warnings": list(dict.fromkeys(warnings)),
        "summary": summary,
        "performance": performance,
        "items": items,
        "correlation": correlation,
        "sectors": build_sectors(items),
        "note": "等权指数为自选监控指标（归一收盘价均值），不是可交易组合。",
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, numbers.Real):
        number = float(value)
        return number if math.isfinite(number) else None
    return value


async def analyze(
    symbols: str | Sequence[str],
    range_value: str = DEFAULT_RANGE,
) -> dict[str, Any]:
    tickers = parse_symbols(symbols)
    range_key = normalize_range(range_value)
    cache_key = (tuple(tickers), range_key)
    cached = _ANALYZE_CACHE.get(cache_key)
    if cached and cached[0] > time.time():
        return cached[1]
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

    async def load_candles(symbol: str) -> tuple[str, dict[str, Any] | None]:
        async with semaphore:
            try:
                payload = await asyncio.wait_for(
                    eastmoney.candles(symbol, CANDLE_TIMEFRAME), timeout=12
                )
                return symbol, payload
            except Exception as exc:
                logger.info("watchlist candles failed for %s: %s", symbol, exc)
                return symbol, None

    async def load_quotes() -> list[dict[str, Any]] | None:
        try:
            return await asyncio.wait_for(eastmoney.quotes(tickers), timeout=8)
        except Exception as exc:
            logger.info("watchlist quotes failed: %s", exc)
            return None

    async def load_universe() -> dict[str, Any] | None:
        try:
            return await asyncio.wait_for(eastmoney.universe(3000), timeout=10)
        except Exception as exc:
            logger.info("watchlist universe failed: %s", exc)
            return None

    async def load_benchmark() -> list[dict[str, Any]] | None:
        try:
            return await asyncio.wait_for(
                nasdaq.historical_etf(BENCHMARK_SYMBOL, BENCHMARK_DAYS), timeout=10
            )
        except Exception as exc:
            logger.info("watchlist benchmark failed: %s", exc)
            return None

    candle_pairs, quote_items, universe_data, benchmark_bars = await asyncio.gather(
        asyncio.gather(*(load_candles(symbol) for symbol in tickers)),
        load_quotes(),
        load_universe(),
        load_benchmark(),
    )
    payload_map = {symbol: payload for symbol, payload in candle_pairs if payload}
    quote_map: dict[str, dict[str, Any]] = {}
    for quote in quote_items or []:
        if not isinstance(quote, dict):
            continue
        symbol = _text(quote.get("symbol")).upper()
        if symbol:
            quote_map[symbol] = quote
    universe_items = (
        (universe_data or {}).get("items") or []
        if isinstance(universe_data, dict)
        else []
    )

    load_warnings: list[str] = []
    if not quote_items:
        load_warnings.append("实时报价暂不可用，价格与涨跌幅已按日线估算。")
    if universe_data is None:
        load_warnings.append("全市场快照暂不可用，行业、PE/PB 与市值可能缺失。")
    if not benchmark_bars:
        load_warnings.append("SPY 基准暂不可用，绩效曲线的基准部分为空。")

    result = await asyncio.to_thread(
        _build_payload,
        tickers,
        payload_map,
        quote_map,
        universe_items,
        benchmark_bars,
        range_key,
    )
    result["warnings"] = list(dict.fromkeys(load_warnings + result["warnings"]))
    safe_result = _json_safe(result)
    if len(_ANALYZE_CACHE) >= 32:
        _ANALYZE_CACHE.pop(next(iter(_ANALYZE_CACHE)))
    _ANALYZE_CACHE[cache_key] = (time.time() + ANALYZE_CACHE_TTL, safe_result)
    return safe_result
