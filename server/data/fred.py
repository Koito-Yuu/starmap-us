from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from server.config import CACHE_DIR, FRED_HEADERS, MACRO_SERIES
from server.data.cache import JsonCache
from server.data.http import http

logger = logging.getLogger(__name__)
cache = JsonCache(CACHE_DIR)
BASE = "https://fred.stlouisfed.org/graph/fredgraph.csv"

# 同比期数：日频约一年交易日、周频 52 周、月频 12 个月、季频 4 个季度。
YOY_PERIODS = {"d": 252, "w": 52, "m": 12, "q": 4}
CURVE_WINDOW_YEARS = 12


def _parse_csv(text: str) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    lines = text.strip().splitlines()
    for line in lines[1:]:
        parts = line.split(",")
        if len(parts) < 2:
            continue
        date_value, raw = parts[0].strip(), parts[1].strip()
        if not date_value or raw in ("", "."):
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        points.append({"d": date_value, "v": round(value, 4)})
    return points


async def series_raw(series_id: str, years: int = 10) -> list[dict[str, Any]]:
    if series_id not in MACRO_SERIES:
        raise ValueError(f"unsupported FRED series {series_id}")
    key = f"fred:v2:{series_id}:{years}"

    async def factory() -> list[dict[str, Any]]:
        start = (datetime.now() - timedelta(days=int(years * 365.25) + 40)).strftime("%Y-%m-%d")
        text = await http.get_text(
            BASE,
            params={"id": series_id, "cosd": start},
            headers=FRED_HEADERS,
        )
        return _parse_csv(text)

    return await cache.get(key, 3600, factory)


def _yoy(points: list[dict[str, Any]], periods: int = 12) -> list[dict[str, Any]]:
    """按观测期数计算同比百分比。

    数据源为 FRED 原始序列，日期保留上游发布日期；periods 与频率对应
    （日 252、周 52、月 12、季 4）。只回看 periods 个观测，不填充未来。
    """
    if len(points) <= periods:
        return []
    result = []
    for index in range(periods, len(points)):
        previous = points[index - periods]["v"]
        if previous == 0:
            continue
        result.append(
            {
                "d": points[index]["d"],
                "v": round((points[index]["v"] / previous - 1) * 100, 2),
            }
        )
    return result


def _annualized_3m(points: list[dict[str, Any]]) -> float | None:
    """按指数点计算 3 个月年化通胀，公式为 (最新/3个月前)^4-1。

    CPI 与核心 CPI 为月频 FRED 指数序列，通常较统计月份滞后数周发布；
    计算只使用最新点及之前 3 个观测，不做任何外推或未来填充。
    """
    if len(points) < 4:
        return None
    latest = points[-1]["v"]
    base = points[-4]["v"]
    if base <= 0:
        return None
    return round(((latest / base) ** 4 - 1) * 100, 2)


def _sample(points: list[dict[str, Any]], max_points: int = 280) -> list[dict[str, Any]]:
    """等距抽样并严格保留首尾，返回不超过 max_points 个点。"""
    if len(points) <= max_points:
        return points
    if max_points <= 1:
        return points[-1:]
    step = (len(points) - 1) / (max_points - 1)
    indices = sorted({int(round(index * step)) for index in range(max_points)})
    indices[-1] = len(points) - 1
    return [points[index] for index in indices]


def _window(
    points: list[dict[str, Any]], years: int, max_points: int = 320
) -> list[dict[str, Any]]:
    if not points:
        return []
    try:
        anchor = datetime.strptime(points[-1]["d"], "%Y-%m-%d")
    except ValueError:
        return _sample(points, max_points)
    cutoff = (anchor - timedelta(days=int(years * 365.25))).strftime("%Y-%m-%d")
    return _sample([point for point in points if point["d"] >= cutoff], max_points)


def _last(points: list[dict[str, Any]]) -> dict[str, Any] | None:
    return points[-1] if points else None


def _value(points: list[dict[str, Any]]) -> float | None:
    latest = _last(points)
    return latest["v"] if latest else None


def _date(points: list[dict[str, Any]]) -> str | None:
    latest = _last(points)
    return latest["d"] if latest else None


def _latest_date(*groups: list[dict[str, Any]]) -> str | None:
    dates = [group[-1]["d"] for group in groups if group]
    return max(dates) if dates else None


def _delta(points: list[dict[str, Any]], back: int) -> float | None:
    if back < 1 or len(points) <= back:
        return None
    return round(points[-1]["v"] - points[-1 - back]["v"], 4)


def _point_on_or_before(
    points: list[dict[str, Any]], target: str
) -> dict[str, Any] | None:
    for point in reversed(points):
        if point["d"] <= target:
            return point
    return None


def _format(value: float | None, digits: int = 2, suffix: str = "") -> str:
    return "—" if value is None else f"{value:.{digits}f}{suffix}"


def _rolling_mean(
    points: list[dict[str, Any]], window: int
) -> list[dict[str, Any]]:
    if window < 1 or len(points) < window:
        return []
    result = []
    for index in range(window - 1, len(points)):
        values = [point["v"] for point in points[index - window + 1 : index + 1]]
        result.append(
            {
                "d": points[index]["d"],
                "v": round(sum(values) / window, 4),
            }
        )
    return result


def _cfnai_3m(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """CFNAI 3 个月均值（芝加哥联储月频活动指数）。

    该指数通常较统计月份滞后约一个月发布；3 月均值用于降低单月噪声。
    这里只做向后滚动平均，不使用未来观测。
    """
    return _rolling_mean(points, 3)


def _claims_4wk(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """ICSA 初请失业金人数的 4 周均值（周频，单位：人）。

    ICSA 通常每周四发布截至前一周的数据，存在约一周发布滞后；
    4 周均值可降低节日与天气造成的周度噪声。
    """
    if len(points) < 4:
        return []
    result = []
    for index in range(3, len(points)):
        values = [point["v"] for point in points[index - 3 : index + 1]]
        result.append({"d": points[index]["d"], "v": round(sum(values) / 4, 1)})
    return result


def _claims_yoy(claims_4wk: list[dict[str, Any]]) -> float | None:
    """初请 4 周均值同比（本周 4 周均值 vs 上年同周），不足 53 个周均值返回 None。"""
    if len(claims_4wk) <= 52:
        return None
    previous = claims_4wk[-1 - 52]["v"]
    if previous == 0:
        return None
    return round((claims_4wk[-1]["v"] / previous - 1) * 100, 2)


def _payroll_changes(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """PAYEMS 非农就业的月度环比变化（单位：千人，FRED 原始单位即千人）。"""
    changes = []
    for index in range(1, len(points)):
        changes.append(
            {
                "d": points[index]["d"],
                "v": round(points[index]["v"] - points[index - 1]["v"], 1),
            }
        )
    return changes


def _align_pairs(
    left: list[dict[str, Any]], right: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    right_map = {point["d"]: point["v"] for point in right}
    pairs = [
        {"d": point["d"], "left": point["v"], "right": right_map[point["d"]]}
        for point in left
        if point["d"] in right_map
    ]
    pairs.sort(key=lambda item: item["d"])
    return pairs


def _spread_points(
    long_points: list[dict[str, Any]], short_points: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """按同一日期计算“长期收益率 - 短期收益率”，只使用两边都已发布的日期。"""
    short_map = {point["d"]: point["v"] for point in short_points}
    points = [
        {"d": point["d"], "v": round(point["v"] - short_map[point["d"]], 3)}
        for point in long_points
        if point["d"] in short_map
    ]
    points.sort(key=lambda item: item["d"])
    return points


def _curve_spread_stats(name: str, points: list[dict[str, Any]]) -> dict[str, Any]:
    """单条期限利差的当前值、一年变化与历史倒挂观测数。

    数据来自 FRED 日频利率/利差；倒挂天数按已加载的近 12 年日频观测计数，
    不是连续日历天数。只使用最新点及以前的数据。
    """
    latest = _last(points)
    if not latest:
        return {
            "name": name,
            "current": None,
            "change_1y": None,
            "inverted": False,
            "inverted_days": None,
            "as_of": None,
        }
    target = (
        datetime.strptime(latest["d"], "%Y-%m-%d") - timedelta(days=365)
    ).strftime("%Y-%m-%d")
    prior = _point_on_or_before(points, target)
    return {
        "name": name,
        "current": round(latest["v"], 3),
        "change_1y": round(latest["v"] - prior["v"], 3) if prior else None,
        "inverted": latest["v"] < 0,
        "inverted_days": sum(1 for point in points if point["v"] < 0),
        "as_of": latest["d"],
    }


def _curve_regime(
    dgs10: list[dict[str, Any]],
    dgs2: list[dict[str, Any]],
    lookback: int = 21,
) -> dict[str, Any]:
    """用截至最新交易日的过去 21 个交易日变化判定曲线形态。

    牛/熊由 10Y 长端方向定义，陡/平由 10Y-2Y 利差变化定义；只回看
    已发布数据，无前视或未来填充。
    """
    pairs = _align_pairs(dgs10, dgs2)
    if len(pairs) <= lookback:
        return {
            "id": "unknown",
            "label": "数据不足",
            "detail": f"10Y 与 2Y 的共同交易日不足 {lookback + 1} 个，暂无法判定曲线形态。",
            "window": lookback,
            "as_of": None,
            "change_10y": None,
            "change_2y": None,
            "change_spread": None,
        }
    start = pairs[-1 - lookback]
    end = pairs[-1]
    change_10y = round(end["left"] - start["left"], 3)
    change_2y = round(end["right"] - start["right"], 3)
    change_spread = round(change_10y - change_2y, 3)
    if change_10y < 0:
        bull = True
    elif change_10y > 0:
        bull = False
    else:
        bull = change_2y <= 0
    steep = change_spread > 0
    if bull and steep:
        regime_id, label = "bull_steepener", "牛陡"
    elif bull and not steep:
        regime_id, label = "bull_flattener", "牛平"
    elif steep:
        regime_id, label = "bear_steepener", "熊陡"
    else:
        regime_id, label = "bear_flattener", "熊平"
    detail = (
        f"过去 {lookback} 个交易日：10Y {change_10y:+.2f} 个百分点，"
        f"2Y {change_2y:+.2f} 个百分点，10Y-2Y 利差 {change_spread:+.2f} 个百分点，"
        f"归类为{label}。区间 {start['d']} 至 {end['d']}。"
    )
    return {
        "id": regime_id,
        "label": label,
        "detail": detail,
        "window": lookback,
        "as_of": end["d"],
        "change_10y": change_10y,
        "change_2y": change_2y,
        "change_spread": change_spread,
    }


def _percentile(
    points: list[dict[str, Any]], value: float | None, years: int = 12
) -> float | None:
    """当前值在最近 N 年同序列历史中的百分位（0-100）。

    以序列最新日期为锚点向前取 N 年，只使用已发布历史；样本不足返回 None。
    """
    latest = _last(points)
    if value is None or not latest:
        return None
    try:
        anchor = datetime.strptime(latest["d"], "%Y-%m-%d")
    except ValueError:
        return None
    cutoff = (anchor - timedelta(days=int(years * 365.25))).strftime("%Y-%m-%d")
    window = [point["v"] for point in points if cutoff <= point["d"] <= latest["d"]]
    if not window:
        return None
    return round(sum(1 for item in window if item <= value) / len(window) * 100, 1)


def _real_policy_series(
    fedfunds: list[dict[str, Any]], cpi_yoy: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """近似实际政策利率：月度 FEDFUNDS 减同月 CPI 同比。

    FRED 的 FEDFUNDS 为月均有效利率，CPI 同比通常滞后数周发布；两者按
    月份对齐，只使用共同存在的月份，因此这是一个近似口径，不是实时值。
    """
    cpi_map = {point["d"][:7]: point for point in cpi_yoy}
    result = []
    for point in fedfunds:
        month = point["d"][:7]
        cpi = cpi_map.get(month)
        if cpi is None:
            continue
        result.append(
            {
                "d": point["d"],
                "v": round(point["v"] - cpi["v"], 2),
            }
        )
    result.sort(key=lambda item: item["d"])
    return result


def _cycle_phase(x: float | None, y: float | None) -> tuple[str, str]:
    """按增长/通胀四象限返回 (phase, label)。"""
    if x is None or y is None:
        return "unknown", "数据不足"
    if x >= 0 and y < 2:
        return "recovery", "复苏"
    if x >= 0 and y >= 2:
        return "reflation", "再通胀"
    if y < 2:
        return "slowdown", "放缓"
    return "stagflation", "滞胀"


def _cycle_analysis(
    cfnai_3m: list[dict[str, Any]], core_cpi_yoy: list[dict[str, Any]]
) -> dict[str, Any]:
    """按月份对齐 CFNAI 3 月均值与核心 CPI 同比，构造最近 36 个月周期轨迹。

    CFNAI 为月频且通常滞后约一个月发布，核心 CPI 为月频；只输出两者都有
    观测的月份。x 以 0 为趋势中性，y 以 2% 为参考，属于环境分类而非预测。
    """
    cfnai_map = {point["d"][:7]: point["v"] for point in cfnai_3m}
    cpi_map = {point["d"][:7]: point["v"] for point in core_cpi_yoy}
    months = sorted(set(cfnai_map) & set(cpi_map))
    trail = []
    for month in months:
        x = cfnai_map.get(month)
        y = cpi_map.get(month)
        if x is None or y is None:
            continue
        trail.append(
            {
                "date": f"{month}-01",
                "x": round(x, 4),
                "y": round(y, 2),
            }
        )
    trail = trail[-36:]
    if not trail:
        return {
            "phase": "unknown",
            "label": "数据不足",
            "x": None,
            "y": None,
            "latest_date": None,
            "as_of": None,
            "detail": "CFNAI 3 月均值与核心 CPI 同比暂无共同月份，无法分类。",
            "trail": [],
            "thresholds": {
                "growth": 0.0,
                "inflation": 2.0,
                "note": "x=CFNAI 3 月均值，0 为趋势中性；y=核心 CPI 同比，2% 为参考。",
            },
        }
    latest = trail[-1]
    phase, label = _cycle_phase(latest["x"], latest["y"])
    detail = (
        f"增长轴 x=CFNAI 3 月均值 {latest['x']:+.2f}（0 为趋势中性），"
        f"通胀轴 y=核心 CPI 同比 {latest['y']:.2f}%（2% 为参考），"
        f"当前处于{label}。这是增长与通胀的环境分类，不是预测。"
    )
    return {
        "phase": phase,
        "label": label,
        "x": latest["x"],
        "y": latest["y"],
        "latest_date": latest["date"],
        "as_of": latest["date"],
        "detail": detail,
        "trail": trail,
        "thresholds": {
            "growth": 0.0,
            "inflation": 2.0,
            "note": "x=CFNAI 3 月均值，0 为趋势中性；y=核心 CPI 同比，2% 为参考。",
        },
    }


def _card(
    series_id: str,
    points: list[dict[str, Any]],
    *,
    label: str | None = None,
    back: int = 1,
    delta_label: str = "较上期",
    decimals: int = 2,
    unit: str | None = None,
) -> dict[str, Any] | None:
    latest = _last(points)
    if not latest:
        return None
    meta = MACRO_SERIES.get(series_id, {})
    return {
        "id": series_id,
        "label": label or meta.get("label", series_id),
        "value": latest["v"],
        "unit": unit if unit is not None else meta.get("unit", ""),
        "decimals": decimals,
        "delta": _delta(points, back),
        "delta_label": delta_label,
        "as_of": latest["d"],
    }


def _sahm(points: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], float | None, bool]:
    values = [point["v"] for point in points]
    dates = [point["d"] for point in points]
    averages = []
    for index in range(2, len(values)):
        averages.append(sum(values[index - 2 : index + 1]) / 3)
    average_dates = dates[2:]
    series = []
    for index in range(12, len(averages)):
        baseline = min(averages[index - 12 : index])
        series.append({"d": average_dates[index], "v": round(averages[index] - baseline, 3)})
    latest = series[-1]["v"] if series else None
    return series, latest, bool(latest is not None and latest >= 0.5)


def _signal(
    level: str, title: str, detail: str, signal_id: str | None = None
) -> dict[str, str]:
    item = {"level": level, "title": title, "detail": detail}
    if signal_id:
        item["id"] = signal_id
    return item


def _tone(status: str) -> str:
    return {
        "triggered": "danger",
        "watch": "warning",
        "clear": "ok",
        "unknown": "neutral",
    }[status]


def _watch_item(
    watch_id: str,
    label: str,
    status: str,
    value: float | None,
    detail: str,
    as_of: str | None,
    threshold_note: str,
    *,
    inverted_days: int | None = None,
) -> dict[str, Any]:
    item = {
        "id": watch_id,
        "label": label,
        "status": status,
        "tone": _tone(status),
        "value": value,
        "detail": detail,
        "as_of": as_of,
        "threshold_note": threshold_note,
    }
    if inverted_days is not None:
        item["inverted_days"] = inverted_days
    return item


async def macro_overview() -> dict[str, Any]:
    async def factory() -> dict[str, Any]:
        ids = list(MACRO_SERIES.keys())
        semaphore = asyncio.Semaphore(5)

        async def one(series_id: str) -> tuple[str, list[dict[str, Any]]]:
            async with semaphore:
                try:
                    return series_id, await series_raw(series_id, years=CURVE_WINDOW_YEARS)
                except Exception as exc:
                    logger.warning("FRED %s failed: %s", series_id, exc)
                    return series_id, []

        raw = dict(await asyncio.gather(*(one(series_id) for series_id in ids)))

        cpi_raw = raw.get("CPIAUCSL", [])
        core_cpi_raw = raw.get("CPILFESL", [])
        cpi_yoy = _yoy(cpi_raw, 12)
        core_yoy = _yoy(core_cpi_raw, 12)
        core_pce_yoy = _yoy(raw.get("PCEPILFE", []), 12)
        gdp_yoy = _yoy(raw.get("GDPC1", []), 4)
        permit_yoy = _yoy(raw.get("PERMIT", []), 12)
        m2_yoy = _yoy(raw.get("M2SL", []), 12)
        walcl_yoy = _yoy(raw.get("WALCL", []), 52)
        sahm_series, sahm_latest, sahm_triggered = _sahm(raw.get("UNRATE", []))

        claims_series = _claims_4wk(raw.get("ICSA", []))
        claims_latest = _last(claims_series)
        claims_yoy = _claims_yoy(claims_series)
        payroll_changes = _payroll_changes(raw.get("PAYEMS", []))
        payroll_latest = _last(payroll_changes)
        payroll_1m = payroll_latest["v"] if payroll_latest else None
        payroll_3m_avg = (
            round(sum(point["v"] for point in payroll_changes[-3:]) / 3, 1)
            if len(payroll_changes) >= 3
            else None
        )
        cfnai_3m = _cfnai_3m(raw.get("CFNAI", []))
        cfnai_latest = _last(cfnai_3m)

        real_policy_series = _real_policy_series(raw.get("FEDFUNDS", []), cpi_yoy)
        real_policy_latest = _last(real_policy_series)

        target_upper_points = raw.get("DFEDTARU", [])
        target_lower_points = raw.get("DFEDTARL", [])
        target_upper = _value(target_upper_points)
        target_lower = _value(target_lower_points)
        target_mid = (
            round((target_upper + target_lower) / 2, 3)
            if target_upper is not None and target_lower is not None
            else None
        )
        target_anchor = _latest_date(target_upper_points, target_lower_points)

        def target_mid_at(days_back: int) -> float | None:
            if not target_anchor:
                return None
            target_date = (
                datetime.strptime(target_anchor, "%Y-%m-%d") - timedelta(days=days_back)
            ).strftime("%Y-%m-%d")
            upper = _point_on_or_before(target_upper_points, target_date)
            lower = _point_on_or_before(target_lower_points, target_date)
            if not upper or not lower:
                return None
            return round((upper["v"] + lower["v"]) / 2, 3)

        target_mid_6m = target_mid_at(182)
        target_mid_12m = target_mid_at(365)
        policy_real_pce = (
            round(target_mid - _value(core_pce_yoy), 2)
            if target_mid is not None and _value(core_pce_yoy) is not None
            else None
        )

        reserves_points = raw.get("WRESBAL", [])
        reserves_latest = _last(reserves_points)
        reserves_change_13w_bn = (
            round((reserves_points[-1]["v"] - reserves_points[-14]["v"]) / 1000, 1)
            if len(reserves_points) >= 14
            else None
        )
        rrp_points = raw.get("RRPONTSYD", [])
        rrp_latest = _last(rrp_points)

        policy_corridor_series = {
            "target_upper": _window(target_upper_points, 5, 320),
            "target_lower": _window(target_lower_points, 5, 320),
            "effective": _window(raw.get("EFFR", []), 5, 320),
            "sofr": _window(raw.get("SOFR", []), 5, 320),
            "iorb": _window(raw.get("IORB", []), 5, 320),
        }

        terms = [
            ("3M", "DGS3MO"),
            ("2Y", "DGS2"),
            ("5Y", "DGS5"),
            ("10Y", "DGS10"),
            ("30Y", "DGS30"),
        ]
        term_dates = [
            raw[sid][-1]["d"] for _, sid in terms if raw.get(sid)
        ]
        curve_anchor = max(term_dates) if term_dates else None
        prior_target = (
            (datetime.strptime(curve_anchor, "%Y-%m-%d") - timedelta(days=365)).strftime(
                "%Y-%m-%d"
            )
            if curve_anchor
            else None
        )
        curve_now = []
        curve_last_year = []
        for term, series_id in terms:
            points = raw.get(series_id, [])
            latest = _last(points)
            if latest:
                curve_now.append({"term": term, "value": latest["v"]})
            if prior_target:
                prior = _point_on_or_before(points, prior_target)
                if prior:
                    curve_last_year.append({"term": term, "value": prior["v"]})

        spread_30y5y = _spread_points(
            raw.get("DGS30", []), raw.get("DGS5", [])
        )
        curve_spreads = [
            _curve_spread_stats("10Y-2Y", raw.get("T10Y2Y", [])),
            _curve_spread_stats("10Y-3M", raw.get("T10Y3M", [])),
            _curve_spread_stats("30Y-5Y", spread_30y5y),
        ]
        curve_regime = _curve_regime(raw.get("DGS10", []), raw.get("DGS2", []), 21)

        hy_points = raw.get("BAMLH0A0HYM2", [])
        hy_latest = _last(hy_points)
        hy_value = hy_latest["v"] if hy_latest else None
        hy_change_1m = _delta(hy_points, 21)
        hy_change_3m = _delta(hy_points, 63)
        # FRED limits BAMLH0A0HYM2 to a rolling ~3-year window; never label it as 12y.
        hy_percentile = _percentile(hy_points, hy_value, years=3)
        baa_points = raw.get("BAA10Y", [])
        baa_latest = _last(baa_points)
        baa_value = baa_latest["v"] if baa_latest else None

        nfci_points = raw.get("NFCI", [])
        nfci_latest = _last(nfci_points)
        nfci_value = nfci_latest["v"] if nfci_latest else None
        nfci_change_4w = _delta(nfci_points, 4)

        walcl_points = raw.get("WALCL", [])
        walcl_latest = _last(walcl_points)
        fed_balance_change_13w_bn = (
            round((walcl_points[-1]["v"] - walcl_points[-14]["v"]) / 1000, 1)
            if len(walcl_points) >= 14
            else None
        )
        if fed_balance_change_13w_bn is None:
            liquidity_direction = "未知"
        elif fed_balance_change_13w_bn > 0:
            liquidity_direction = "扩张"
        elif fed_balance_change_13w_bn < 0:
            liquidity_direction = "收缩"
        else:
            liquidity_direction = "持平"

        policy_balance_sheet = {
            "total_assets_trillion": (
                round(walcl_latest["v"] / 1e6, 3) if walcl_latest else None
            ),
            "total_assets_change_13w_bn": fed_balance_change_13w_bn,
            "reserves_trillion": (
                round(reserves_latest["v"] / 1e6, 3) if reserves_latest else None
            ),
            "reserves_change_13w_bn": reserves_change_13w_bn,
            "on_rrp_bn": round(rrp_latest["v"], 1) if rrp_latest else None,
            "as_of": _latest_date(
                walcl_points, reserves_points, rrp_points
            ),
        }
        policy = {
            "target_lower": target_lower,
            "target_upper": target_upper,
            "target_mid": target_mid,
            "effective": _value(raw.get("EFFR", [])),
            "sofr": _value(raw.get("SOFR", [])),
            "iorb": _value(raw.get("IORB", [])),
            "real_policy_pce": policy_real_pce,
            "core_pce_yoy": _value(core_pce_yoy),
            "target_change_6m": (
                round(target_mid - target_mid_6m, 3)
                if target_mid is not None and target_mid_6m is not None
                else None
            ),
            "target_change_12m": (
                round(target_mid - target_mid_12m, 3)
                if target_mid is not None and target_mid_12m is not None
                else None
            ),
            "balance_sheet": policy_balance_sheet,
            "as_of": _latest_date(
                target_upper_points,
                target_lower_points,
                raw.get("EFFR", []),
                raw.get("SOFR", []),
                raw.get("IORB", []),
            ),
            "note": "目标区间来自 DFEDTARU/DFEDTARL；EFFR、SOFR、IORB 为 FRED 官方发布值。实际政策利率使用目标中值减核心 PCE 同比，属于事后近似。",
        }

        cfnai_raw_latest = _last(raw.get("CFNAI", []))
        permit_yoy_latest = _last(permit_yoy)
        inflation_as_of = _latest_date(
            cpi_yoy,
            core_yoy,
            core_pce_yoy,
            raw.get("T10YIE", []),
            raw.get("T5YIFR", []),
        )
        labor_as_of = _latest_date(
            raw.get("UNRATE", []), claims_series, payroll_changes
        )
        credit_as_of = _latest_date(hy_points, baa_points, nfci_points)
        liquidity_as_of = _latest_date(m2_yoy, walcl_yoy)
        growth_as_of = _latest_date(
            gdp_yoy,
            raw.get("CFNAI", []),
            cfnai_3m,
            permit_yoy,
            raw.get("UMCSENT", []),
        )

        inflation = {
            "cpi_yoy": _value(cpi_yoy),
            "core_cpi_yoy": _value(core_yoy),
            "core_pce_yoy": _value(core_pce_yoy),
            "cpi_3m_annualized": _annualized_3m(cpi_raw),
            "core_3m_annualized": _annualized_3m(core_cpi_raw),
            "breakeven": _value(raw.get("T10YIE", [])),
            "forward5y5y": _value(raw.get("T5YIFR", [])),
            "as_of": {
                "cpi_yoy": _date(cpi_yoy),
                "core_cpi_yoy": _date(core_yoy),
                "core_pce_yoy": _date(core_pce_yoy),
                "cpi_3m_annualized": _date(cpi_raw),
                "core_3m_annualized": _date(core_cpi_raw),
                "breakeven": _date(raw.get("T10YIE", [])),
                "forward5y5y": _date(raw.get("T5YIFR", [])),
            },
            "note": "3 个月年化按指数点计算：(最新/3个月前)^4-1；为月频发布口径。",
        }
        if inflation_as_of:
            inflation["latest_date"] = inflation_as_of

        real_rates = {
            "nominal10": _value(raw.get("DGS10", [])),
            "real10": _value(raw.get("DFII10", [])),
            "breakeven10": _value(raw.get("T10YIE", [])),
            "forward_5y5y": _value(raw.get("T5YIFR", [])),
            "real_policy": real_policy_latest["v"] if real_policy_latest else None,
            "cpi": _value(cpi_yoy),
            "cpi_core": _value(core_yoy),
            "core_pce": _value(core_pce_yoy),
            "change_1m": {
                "nominal10": _delta(raw.get("DGS10", []), 21),
                "real10": _delta(raw.get("DFII10", []), 21),
                "breakeven10": _delta(raw.get("T10YIE", []), 21),
                "forward_5y5y": _delta(raw.get("T5YIFR", []), 21),
                "real_policy": _delta(real_policy_series, 1),
                "cpi": _delta(cpi_yoy, 1),
                "cpi_core": _delta(core_yoy, 1),
                "core_pce": _delta(core_pce_yoy, 1),
            },
            "as_of": {
                "nominal10": _date(raw.get("DGS10", [])),
                "real10": _date(raw.get("DFII10", [])),
                "breakeven10": _date(raw.get("T10YIE", [])),
                "forward_5y5y": _date(raw.get("T5YIFR", [])),
                "real_policy": _date(real_policy_series),
                "cpi": _date(cpi_yoy),
                "cpi_core": _date(core_yoy),
                "core_pce": _date(core_pce_yoy),
            },
            "note": "实际政策利率=联邦基金利率-CPI同比，按共同月份近似；日频变化按21个交易日，月频按1个月。",
        }
        if inflation_as_of:
            real_rates["latest_date"] = inflation_as_of

        labor = {
            "unrate": _value(raw.get("UNRATE", [])),
            "sahm": sahm_latest,
            "claims_4wk": claims_latest["v"] if claims_latest else None,
            "claims_yoy": claims_yoy,
            "payroll_1m": payroll_1m,
            "payroll_3m_avg": payroll_3m_avg,
            "payroll_1m_change": payroll_1m,
            "payroll_3m_avg_change": payroll_3m_avg,
            "as_of": {
                "unrate": _date(raw.get("UNRATE", [])),
                "sahm": _date(sahm_series),
                "claims_4wk": _date(claims_series),
                "claims_yoy": _date(claims_series),
                "payroll_1m": _date(payroll_changes),
                "payroll_3m_avg": _date(payroll_changes),
                "payroll_1m_change": _date(payroll_changes),
                "payroll_3m_avg_change": _date(payroll_changes),
            },
            "description": "初请失业金为周频领先指标（通常滞后约一周发布）；非农与失业率为月频，Sahm 为基于失业率的近似规则。",
        }
        if labor_as_of:
            labor["latest_date"] = labor_as_of

        credit = {
            "hy_oas": hy_value,
            "hy_change_1m": hy_change_1m,
            "hy_change_3m": hy_change_3m,
            "hy_percentile_available": hy_percentile,
            "hy_percentile_12y": hy_percentile,
            "baa10y": baa_value,
            "baa_change_3m": _delta(baa_points, 63),
            "nfci": nfci_value,
            "nfci_change_4w": nfci_change_4w,
            "as_of": {
                "hy_oas": _date(hy_points),
                "hy_change_1m": _date(hy_points),
                "hy_change_3m": _date(hy_points),
                "hy_percentile_12y": _date(hy_points),
                "nfci": _date(nfci_points),
                "nfci_change_4w": _date(nfci_points),
            },
            "description": "高收益 OAS 为日频信用利差，但 FRED 自 2026 年起只保留约 3 年；Baa-10Y 利差用于较长历史。NFCI 为周频金融条件指数（有发布滞后）；以下只描述状态，不做综合评分。",
        }
        if credit_as_of:
            credit["latest_date"] = credit_as_of

        liquidity = {
            "m2_yoy": _value(m2_yoy),
            "walcl_yoy": _value(walcl_yoy),
            "fed_balance_change_13w_bn": fed_balance_change_13w_bn,
            "direction": liquidity_direction,
            "as_of": {
                "m2_yoy": _date(m2_yoy),
                "walcl_yoy": _date(walcl_yoy),
                "fed_balance_change_13w_bn": _date(walcl_points),
            },
            "description": "M2 为月频、WALCL 为周频；13 周变化由百万美元除以 1000 换算为十亿美元。",
        }
        if liquidity_as_of:
            liquidity["latest_date"] = liquidity_as_of

        growth = {
            "gdp_yoy": _value(gdp_yoy),
            "cfnai": cfnai_raw_latest["v"] if cfnai_raw_latest else None,
            "cfnai_3m": cfnai_latest["v"] if cfnai_latest else None,
            "permits_yoy": permit_yoy_latest["v"] if permit_yoy_latest else None,
            "permit_yoy": permit_yoy_latest["v"] if permit_yoy_latest else None,
            "consumer_sentiment": _value(raw.get("UMCSENT", [])),
            "as_of": {
                "gdp_yoy": _date(gdp_yoy),
                "cfnai": _date(raw.get("CFNAI", [])),
                "cfnai_3m": _date(cfnai_3m),
                "permits_yoy": _date(permit_yoy),
                "permit_yoy": _date(permit_yoy),
                "consumer_sentiment": _date(raw.get("UMCSENT", [])),
            },
            "description": "GDP 为季频滞后指标；CFNAI 为月频且通常滞后约一个月；新屋许可为月频领先地产投资；消费者信心为月频。",
        }
        if growth_as_of:
            growth["latest_date"] = growth_as_of

        cycle = _cycle_analysis(cfnai_3m, core_yoy)

        t10y3m_points = raw.get("T10Y3M", [])
        t10y3m_latest = _last(t10y3m_points)
        t10y3m_value = t10y3m_latest["v"] if t10y3m_latest else None
        t10y3m_inverted_days = (
            sum(1 for point in t10y3m_points if point["v"] < 0)
            if t10y3m_points
            else None
        )
        if t10y3m_value is None:
            t10y3m_status = "unknown"
        elif t10y3m_value < 0:
            t10y3m_status = "triggered"
        elif t10y3m_value < 0.25:
            t10y3m_status = "watch"
        else:
            t10y3m_status = "clear"

        if sahm_latest is None:
            sahm_status = "unknown"
        elif sahm_latest >= 0.5:
            sahm_status = "triggered"
        elif sahm_latest >= 0.3:
            sahm_status = "watch"
        else:
            sahm_status = "clear"

        if claims_yoy is None:
            claims_status = "unknown"
        elif claims_yoy >= 25:
            claims_status = "triggered"
        elif claims_yoy >= 10:
            claims_status = "watch"
        else:
            claims_status = "clear"

        cfnai_3m_value = cfnai_latest["v"] if cfnai_latest else None
        if cfnai_3m_value is None:
            cfnai_status = "unknown"
        elif cfnai_3m_value < -0.7:
            cfnai_status = "triggered"
        elif cfnai_3m_value < -0.35:
            cfnai_status = "watch"
        else:
            cfnai_status = "clear"

        if hy_value is None:
            hy_status = "unknown"
        elif hy_value >= 5 and hy_change_3m is not None and hy_change_3m > 0:
            hy_status = "triggered"
        elif hy_value >= 5 or (hy_change_3m is not None and hy_change_3m >= 0.5):
            hy_status = "watch"
        else:
            hy_status = "clear"

        if nfci_value is None:
            nfci_status = "unknown"
        elif nfci_value > 0.5:
            nfci_status = "triggered"
        elif nfci_value > 0.2:
            nfci_status = "watch"
        else:
            nfci_status = "clear"

        recession_watch = [
            _watch_item(
                "curve_10y3m",
                "10Y-3M 利差",
                t10y3m_status,
                t10y3m_value,
                (
                    f"10Y-3M 当前 {_format(t10y3m_value, 2, ' 个百分点')}；"
                    f"近 12 年累计倒挂 {t10y3m_inverted_days if t10y3m_inverted_days is not None else '—'} 个交易日。"
                ),
                _date(t10y3m_points),
                "当前值 < 0 视为倒挂触发，0~0.25 为观察区；历史天数按日频观测计数。非概率、非预测。",
                inverted_days=t10y3m_inverted_days,
            ),
            _watch_item(
                "sahm",
                "Sahm 规则",
                sahm_status,
                sahm_latest,
                f"Sahm 近似值 {_format(sahm_latest, 2, ' 个百分点')}（失业率 3 月均值较前 12 个月最低值上行）。",
                _date(sahm_series),
                "≥ 0.50 触发，0.30~0.50 为观察区；基于失业率均值的近似计算。非概率、非预测。",
            ),
            _watch_item(
                "claims_4wk_yoy",
                "初请 4 周同比",
                claims_status,
                claims_yoy,
                (
                    f"初请 4 周均值 {_format(claims_latest['v'] if claims_latest else None, 0, ' 人')}，"
                    f"同比 {_format(claims_yoy, 2, '%')}。"
                ),
                _date(claims_series),
                "4 周均值同比 ≥ 25% 触发，10%~25% 为观察区；ICSA 为周频且通常滞后约一周。非概率、非预测。",
            ),
            _watch_item(
                "cfnai_3m",
                "CFNAI 3 月均值",
                cfnai_status,
                cfnai_3m_value,
                f"CFNAI 3 月均值 {_format(cfnai_3m_value, 2)}，0 为趋势中性。",
                _date(cfnai_3m),
                "< -0.70 触发，-0.70~-0.35 为观察区；CFNAI 为月频且通常滞后约一个月。非概率、非预测。",
            ),
            _watch_item(
                "hy_oas",
                "高收益债 OAS",
                hy_status,
                hy_value,
                (
                    f"高收益 OAS {_format(hy_value, 2, '%')}，"
                    f"近 3 个月变化 {_format(hy_change_3m, 2, ' 个百分点')}。"
                ),
                _date(hy_points),
                "OAS ≥ 5% 且 3 个月走阔触发，≥5% 或 3 个月走阔 ≥0.50 个百分点为观察区；仅描述信用环境。非概率、非预测。",
            ),
            _watch_item(
                "nfci",
                "NFCI 金融条件",
                nfci_status,
                nfci_value,
                (
                    f"NFCI {_format(nfci_value, 2)}，"
                    f"近 4 周变化 {_format(nfci_change_4w, 2)}；正值表示金融条件偏紧。"
                ),
                _date(nfci_points),
                "> 0.50 触发，0.20~0.50 为观察区；NFCI 为周频且存在发布滞后。非概率、非预测。",
            ),
        ]

        # 旧 cards 的 10 项及顺序保持不变，新增两项追加在末尾。
        cards = [
            _card("DGS10", raw.get("DGS10", []), back=21, delta_label="较1月前"),
            _card("DGS2", raw.get("DGS2", []), back=21, delta_label="较1月前"),
            _card("T10Y2Y", raw.get("T10Y2Y", []), back=21, delta_label="较1月前"),
            _card("CPIAUCSL", cpi_yoy, label="CPI 同比", back=1, delta_label="较上月", decimals=1),
            _card("CPILFESL", core_yoy, label="核心 CPI 同比", back=1, delta_label="较上月", decimals=1),
            _card("UNRATE", raw.get("UNRATE", []), back=1, delta_label="较上月", decimals=1),
            _card("FEDFUNDS", raw.get("FEDFUNDS", []), back=1, delta_label="较上月"),
            _card("VIXCLS", raw.get("VIXCLS", []), back=21, delta_label="较1月前"),
            _card("DTWEXBGS", raw.get("DTWEXBGS", []), back=21, delta_label="较1月前"),
            _card("GDPC1", gdp_yoy, label="实际 GDP 同比", back=1, delta_label="较上季", decimals=1),
            _card(
                "HY_OAS",
                hy_points,
                label="高收益债 OAS",
                back=21,
                delta_label="较1月前",
                unit="%",
            ),
            _card(
                "CFNAI_3M",
                cfnai_3m,
                label="CFNAI 3月均值",
                back=1,
                delta_label="较上月",
                unit="index",
            ),
        ]
        cards = [card for card in cards if card]

        signals = []
        spread_10y2y = _value(raw.get("T10Y2Y", []))
        spread_10y3m = t10y3m_value
        spread_values = [value for value in (spread_10y2y, spread_10y3m) if value is not None]
        if spread_values:
            inverted = any(value < 0 for value in spread_values)
            signals.append(
                _signal(
                    "warning" if inverted else "ok",
                    "收益率曲线倒挂" if inverted else "收益率曲线正挂",
                    (
                        f"10Y-2Y 利差 {_format(spread_10y2y, 2, ' 个百分点')}，"
                        f"10Y-3M 利差 {_format(spread_10y3m, 2, ' 个百分点')}；"
                        + ("曲线出现倒挂。" if inverted else "曲线整体为正挂。")
                    ),
                    "curve",
                )
            )
        if sahm_latest is not None:
            signals.append(
                _signal(
                    "danger" if sahm_triggered else ("warning" if sahm_latest >= 0.3 else "ok"),
                    "Sahm 规则" + ("已触发" if sahm_triggered else "未触发"),
                    f"当前近似值 {sahm_latest:.2f} 个百分点，阈值 0.50。该指标为基于失业率的近似计算。",
                    "sahm",
                )
            )
        if _value(cpi_yoy) is not None:
            cpi_value = _value(cpi_yoy)
            cpi_3m = _annualized_3m(cpi_raw)
            signals.append(
                _signal(
                    "warning" if cpi_value > 3 else ("ok" if cpi_value <= 2.5 else "neutral"),
                    "通胀温度",
                    (
                        f"CPI 同比 {cpi_value:.1f}%，核心 CPI 同比 {_format(_value(core_yoy), 1, '%')}，"
                        f"核心 PCE 同比 {_format(_value(core_pce_yoy), 1, '%')}，"
                        f"CPI 3 个月年化 {_format(cpi_3m, 1, '%')}；"
                        + ("高于 3%，政策利率下行空间受限。" if cpi_value > 3 else "通胀压力相对温和。")
                    ),
                    "inflation",
                )
            )
        vix_latest = _last(raw.get("VIXCLS", []))
        if vix_latest:
            level = vix_latest["v"]
            signals.append(
                _signal(
                    "warning" if level >= 30 else ("ok" if level < 18 else "neutral"),
                    "市场波动水平",
                    f"VIX 最新 {level:.2f}，"
                    + ("处于高位，风险偏好收缩。" if level >= 30 else "处于低位，风险偏好较强。" if level < 18 else "处于中性区间。"),
                    "vix",
                )
            )
        if hy_value is not None:
            signals.append(
                _signal(
                    "warning" if hy_value >= 5 else ("neutral" if hy_value >= 4 else "ok"),
                    "信用利差",
                    (
                        f"高收益债 OAS {hy_value:.2f}%，较 3 个月前 "
                        f"{_format(hy_change_3m, 2, ' 个百分点')}，"
                        f"处于 FRED 可用约 3 年历史 {_format(hy_percentile, 1, '%')} 分位。"
                    ),
                    "credit",
                )
            )
        if nfci_value is not None:
            signals.append(
                _signal(
                    "warning" if nfci_value > 0.5 else ("neutral" if nfci_value > 0.2 else "ok"),
                    "金融条件",
                    (
                        f"NFCI {nfci_value:.2f}，较 4 周前 {_format(nfci_change_4w, 2)}；"
                        + ("金融条件偏紧。" if nfci_value > 0.5 else "金融条件未显示明显收紧。")
                    ),
                    "nfci",
                )
            )

        def sampled(series_id: str, years: int, max_points: int = 280) -> list[dict[str, Any]]:
            return _window(raw.get(series_id, []), years, max_points)

        growth_series = {
            "gdp_yoy": _window(gdp_yoy, 12, 48),
            "cfnai": sampled("CFNAI", 10, 120),
            "cfnai_3m": _window(cfnai_3m, 10, 120),
            "permits": _window(permit_yoy, 10, 160),
        }
        series_payload = {
            "yields": {
                "DGS3MO": sampled("DGS3MO", 5),
                "DGS2": sampled("DGS2", 5),
                "DGS10": sampled("DGS10", 5),
                "DGS30": sampled("DGS30", 5),
            },
            "spread": sampled("T10Y2Y", 10, 320),
            "inflation": {
                "cpi": _window(cpi_yoy, 10, 160),
                "core": _window(core_yoy, 10, 160),
                "core_pce": _window(core_pce_yoy, 10, 160),
            },
            "labor": {
                "unrate": sampled("UNRATE", 10, 160),
                "sahm": sahm_series[-120:],
                "claims_4wk": _window(claims_series, 5, 160),
                "payroll_change": _window(payroll_changes, 10, 160),
            },
            "policy": {
                "fedfunds": sampled("FEDFUNDS", 10, 160),
                "dgs10": sampled("DGS10", 10, 320),
            },
            "policy_corridor": policy_corridor_series,
            "rates": {
                "real10": sampled("DFII10", 5, 320),
                "breakeven": sampled("T10YIE", 5, 320),
                "forward5y5y": sampled("T5YIFR", 5, 320),
                "fedfunds": sampled("FEDFUNDS", 10, 160),
            },
            "curve_spreads": {
                "t10y2y": sampled("T10Y2Y", 10, 320),
                "t10y3m": sampled("T10Y3M", 10, 320),
                "t5y30y": _window(spread_30y5y, 10, 320),
            },
            "credit": {
                "hy_oas": sampled("BAMLH0A0HYM2", 3, 320),
                "baa10y": sampled("BAA10Y", 10, 320),
                "nfci": sampled("NFCI", 5, 260),
            },
            "liquidity": {
                "m2_yoy": _window(m2_yoy, 10, 160),
                "walcl_yoy": _window(walcl_yoy, 10, 160),
            },
            "vix": sampled("VIXCLS", 3, 220),
            "dollar": sampled("DTWEXBGS", 5, 220),
            "gdp": growth_series,
            "growth": growth_series,
        }
        series_units = {
            "yields.DGS3MO": "%",
            "yields.DGS2": "%",
            "yields.DGS10": "%",
            "yields.DGS30": "%",
            "spread": "% (10Y-2Y)",
            "inflation.cpi": "% YoY",
            "inflation.core": "% YoY",
            "inflation.core_pce": "% YoY",
            "labor.unrate": "%",
            "labor.sahm": "百分点",
            "labor.claims_4wk": "人 (4 周均值)",
            "labor.payroll_change": "千人 (月度环比)",
            "policy.fedfunds": "%",
            "policy.dgs10": "%",
            "policy_corridor.target_upper": "%",
            "policy_corridor.target_lower": "%",
            "policy_corridor.effective": "%",
            "policy_corridor.sofr": "%",
            "policy_corridor.iorb": "%",
            "rates.real10": "%",
            "rates.breakeven": "%",
            "rates.forward5y5y": "%",
            "rates.fedfunds": "%",
            "curve_spreads.t10y2y": "% (10Y-2Y)",
            "curve_spreads.t10y3m": "% (10Y-3M)",
            "curve_spreads.t5y30y": "% (30Y-5Y)",
            "credit.hy_oas": "% (FRED 约 3 年窗口)",
            "credit.baa10y": "% (Baa-10Y)",
            "credit.nfci": "index",
            "liquidity.m2_yoy": "% YoY",
            "liquidity.walcl_yoy": "% YoY",
            "vix": "index",
            "dollar": "index",
            "gdp.gdp_yoy": "% YoY",
            "gdp.cfnai": "index",
            "gdp.cfnai_3m": "index (3 月均值)",
            "gdp.permits": "% YoY",
            "growth.gdp_yoy": "% YoY",
            "growth.cfnai": "index",
            "growth.cfnai_3m": "index (3 月均值)",
            "growth.permits": "% YoY",
        }

        payload = {
            "cards": cards,
            "yield_curve": curve_now,
            "yield_curve_1y": curve_last_year,
            "curve": {
                "current": curve_now,
                "one_year_ago": curve_last_year,
                "1y": curve_last_year,
                "spreads": curve_spreads,
                "spread_note": "均按长期收益率减短期收益率计算，其中 t5y30y 为 30Y-5Y。",
                "regime": curve_regime,
                "window_years": CURVE_WINDOW_YEARS,
                "as_of": curve_anchor,
            },
            "curve_regime": curve_regime,
            "real_rates": real_rates,
            "inflation": inflation,
            "labor": labor,
            "credit": credit,
            "liquidity": liquidity,
            "growth": growth,
            "policy": policy,
            "cycle": cycle,
            "recession_watch": recession_watch,
            "series": series_payload,
            "series_units": series_units,
            "signals": signals,
            "sahm": {"value": sahm_latest, "triggered": sahm_triggered},
            "spread": spread_10y2y,
            "as_of": max((card["as_of"] for card in cards), default=None),
            "source": "FRED",
            "data_note": "各序列发布频率与修订机制不同。",
        }
        return payload

    return await cache.get("macro:overview:v6", 3600, factory)
