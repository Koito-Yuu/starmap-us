from __future__ import annotations

import math
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

RISK_FREE = 0.04

DEFAULT_INDICATOR_PARAMS: dict[str, Any] = {
    "ma_periods": [5, 20, 50, 200],
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "rsi_period": 14,
    "bb_period": 20,
    "bb_mult": 2,
    "kc_period": 20,
    "kc_atr_period": 20,
    "kc_mult": 2,
    "donchian_period": 20,
    "regression_period": 60,
    "regression_mult": 2,
    "vwap_period": 20,
    "vwap_mult": 2,
    "adaptive_period": 10,
    "adaptive_fast": 2,
    "adaptive_slow": 30,
    "adaptive_atr_period": 14,
    "adaptive_mult": 1.5,
    "supertrend_period": 10,
    "supertrend_mult": 3,
    "kama_period": 10,
    "kama_fast": 2,
    "kama_slow": 30,
    "adx_period": 14,
    "stoch_period": 14,
    "stoch_k": 3,
    "stoch_d": 3,
    "cmf_period": 20,
    "atr_period": 14,
    "squeeze_bb_period": 20,
    "squeeze_bb_mult": 2,
    "squeeze_kc_period": 20,
    "squeeze_kc_mult": 1.5,
    "squeeze_momentum_period": 20,
}

# Generic periods use the documented 2..200 range; the entries below are exceptions.
_INTEGER_PARAM_RANGES = {
    "macd_fast": (2, 100),
    "macd_slow": (3, 200),
    "macd_signal": (2, 100),
    "rsi_period": (2, 200),
    "bb_period": (2, 200),
    "kc_period": (2, 200),
    "kc_atr_period": (2, 200),
    "donchian_period": (2, 200),
    "regression_period": (2, 200),
    "vwap_period": (2, 200),
    "adaptive_period": (2, 200),
    "adaptive_fast": (2, 50),
    "adaptive_slow": (5, 200),
    "adaptive_atr_period": (2, 200),
    "supertrend_period": (2, 200),
    "kama_period": (2, 200),
    "kama_fast": (2, 50),
    "kama_slow": (5, 200),
    "adx_period": (2, 200),
    "stoch_period": (2, 200),
    "stoch_k": (1, 20),
    "stoch_d": (1, 20),
    "cmf_period": (2, 200),
    "atr_period": (2, 200),
    "squeeze_bb_period": (2, 200),
    "squeeze_kc_period": (2, 200),
    "squeeze_momentum_period": (2, 200),
}

_MULTIPLIER_PARAMS = (
    "bb_mult",
    "kc_mult",
    "regression_mult",
    "vwap_mult",
    "adaptive_mult",
    "supertrend_mult",
    "squeeze_bb_mult",
    "squeeze_kc_mult",
)


def _param_int(value: Any, low: int, high: int) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, float) and math.isfinite(value) and value.is_integer():
        number = int(value)
    else:
        return None
    return number if low <= number <= high else None


def _param_mult(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    return number if math.isfinite(number) and 0.5 <= number <= 10 else None


def normalize_indicator_params(raw: Any) -> dict[str, Any]:
    params = {
        key: list(value) if isinstance(value, list) else value
        for key, value in DEFAULT_INDICATOR_PARAMS.items()
    }
    if not isinstance(raw, dict):
        return params

    for key, (low, high) in _INTEGER_PARAM_RANGES.items():
        value = _param_int(raw.get(key), low, high)
        if value is not None:
            params[key] = value
    for key in _MULTIPLIER_PARAMS:
        value = _param_mult(raw.get(key))
        if value is not None:
            params[key] = value

    periods = raw.get("ma_periods")
    if isinstance(periods, (list, tuple)) and len(periods) == 4:
        parsed = [_param_int(period, 2, 300) for period in periods]
        if all(period is not None for period in parsed) and len(set(parsed)) == 4:
            params["ma_periods"] = sorted(parsed)

    for fast_key, slow_key in (
        ("macd_fast", "macd_slow"),
        ("kama_fast", "kama_slow"),
        ("adaptive_fast", "adaptive_slow"),
    ):
        if params[fast_key] >= params[slow_key]:
            params[fast_key] = DEFAULT_INDICATOR_PARAMS[fast_key]
            params[slow_key] = DEFAULT_INDICATOR_PARAMS[slow_key]
    return params


def _clamp(value: float, low: float = 0, high: float = 100) -> float:
    return max(low, min(high, value))


def _interp(points: list[tuple[float, float]], value: float | None) -> float | None:
    if value is None:
        return None
    if value <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if value <= x1:
            return y0 + (y1 - y0) * (value - x0) / (x1 - x0)
    return points[-1][1]


def _median(values: list[float]) -> float | None:
    clean = [value for value in values if value is not None and math.isfinite(value)]
    return float(np.median(clean)) if clean else None


def _percentile_rank(value: float | None, values: list[float]) -> float | None:
    clean = [v for v in values if v is not None and math.isfinite(v)]
    if value is None or len(clean) < 6:
        return None
    less = sum(1 for v in clean if v < value)
    equal = sum(1 for v in clean if v == value)
    return (less + 0.5 * equal) / len(clean) * 100


def sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return float(np.mean(values[-period:]))


def ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2 / (period + 1)
    result = [values[0]]
    for value in values[1:]:
        result.append(alpha * value + (1 - alpha) * result[-1])
    return result


def rsi(values: list[float], period: int = 14) -> float | None:
    series = _rsi_series(values, period)
    return series[-1] if series else None


def _rolling(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    window = 0.0
    for index, value in enumerate(values):
        window += value
        if index >= period:
            window -= values[index - period]
        if index >= period - 1:
            result[index] = round(window / period, 4)
    return result


def _technical_values(values: list[Any]) -> pd.Series:
    clean = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            number = math.nan
        clean.append(number if math.isfinite(number) else math.nan)
    return pd.Series(clean, dtype="float64")


def _technical_export(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _technical_export(series) for key, series in value.items()}
    return [float(item) if item is not None and math.isfinite(item) else None for item in value]


def _technical_smooth(values: pd.Series, period: int, alpha: float) -> pd.Series:
    if period < 1:
        raise ValueError("period must be positive")
    result = np.full(len(values), np.nan)
    count, seed, previous = 0, 0.0, math.nan
    for index, value in enumerate(values.to_numpy()):
        if not math.isfinite(value):
            count, seed, previous = 0, 0.0, math.nan
            continue
        if count < period:
            seed += value / period
            count += 1
            if count < period:
                continue
            previous = seed
        else:
            previous = (1 - alpha) * previous + alpha * value
        if math.isfinite(previous):
            result[index] = previous
        else:
            count, seed, previous = 0, 0.0, math.nan
    return pd.Series(result)


def _rsi_series(values: list[float], period: int = 14) -> list[float | None]:
    if period < 1:
        raise ValueError("period must be positive")
    delta = _technical_values(values).diff()
    gain = _technical_smooth(delta.clip(lower=0), period, 1 / period)
    loss = _technical_smooth((-delta).clip(lower=0), period, 1 / period)
    total = gain + loss
    result = (gain / total.where(total != 0) * 100).mask(total == 0, 50.0)
    return _technical_export(result)


def _technical_ols(values: pd.Series, period: int, mult: float = 2) -> dict[str, pd.Series]:
    result = {key: np.full(len(values), np.nan) for key in ("mid", "upper", "lower", "slope", "r2")}
    if len(values) >= period:
        windows = np.lib.stride_tricks.sliding_window_view(values.to_numpy(), period)
        valid = np.isfinite(windows).all(axis=1)
        indices = np.flatnonzero(valid) + period - 1
        y = windows[valid]
        x = np.arange(period, dtype=float) - (period - 1) / 2
        mean = y.mean(axis=1)
        centered = y - mean[:, None]
        slope = (centered * x).sum(axis=1) / (x * x).sum()
        residual = centered - slope[:, None] * x
        sse = (residual * residual).sum(axis=1)
        sst = (centered * centered).sum(axis=1)
        mid = mean + slope * x[-1]
        width = mult * np.sqrt(sse / period)
        r2 = np.zeros(len(y))
        np.divide(sse, sst, out=r2, where=sst != 0)
        r2 = np.where(sst == 0, 0.0, np.clip(1 - r2, 0, 1))
        for key, data in zip(result, (mid, mid + width, mid - width, slope, r2)):
            result[key][indices] = data
    return {key: pd.Series(data) for key, data in result.items()}


def _technical_vwap(price: pd.Series, volume: pd.Series, period: int,
                    mult: float = 2) -> dict[str, pd.Series]:
    result = {key: np.full(len(price), np.nan) for key in ("mid", "upper", "lower")}
    if len(price) >= period:
        prices = np.lib.stride_tricks.sliding_window_view(price.to_numpy(), period)
        volumes = np.lib.stride_tricks.sliding_window_view(volume.to_numpy(), period)
        totals = volumes.sum(axis=1)
        valid = (np.isfinite(prices).all(axis=1) & np.isfinite(volumes).all(axis=1)
                 & np.isfinite(totals) & (totals > 0))
        indices = np.flatnonzero(valid) + period - 1
        weights = volumes[valid] / totals[valid, None]
        mid = (prices[valid] * weights).sum(axis=1)
        centered = prices[valid] - mid[:, None]
        width = mult * np.sqrt((weights * centered * centered).sum(axis=1))
        for key, data in zip(result, (mid, mid + width, mid - width)):
            result[key][indices] = data
    return {key: pd.Series(data) for key, data in result.items()}


def _technical_kama(close: pd.Series, period: int = 10, fast: int = 2,
                    slow: int = 30) -> tuple[pd.Series, pd.Series]:
    volatility = close.diff().abs().rolling(period, min_periods=period).sum()
    er = (close.diff(period).abs() / volatility.where(volatility != 0)).mask(volatility == 0, 0.0)
    er = er.clip(0, 1)
    result = np.full(len(close), np.nan)
    fast_sc, slow_sc = 2 / (fast + 1), 2 / (slow + 1)
    count, seed, previous = 0, 0.0, math.nan
    for index, value in enumerate(close.to_numpy()):
        if not math.isfinite(value):
            count, seed, previous = 0, 0.0, math.nan
            continue
        count += 1
        if count <= period:
            seed += value / period
            if count < period:
                continue
            previous = seed  # KAMA seed is the SMA of the first period bars; ER updates start next bar.
        else:
            efficiency = er.iat[index]
            if not math.isfinite(efficiency):
                count, seed, previous = 0, 0.0, math.nan
                continue
            alpha = (efficiency * (fast_sc - slow_sc) + slow_sc) ** 2
            previous = (1 - alpha) * previous + alpha * value
        if math.isfinite(previous):
            result[index] = previous
        else:
            count, seed, previous = 0, 0.0, math.nan
    return pd.Series(result), er


def _technical_supertrend(high: pd.Series, low: pd.Series, close: pd.Series,
                          atr: pd.Series | None = None, period: int = 10,
                          mult: float = 3) -> dict[str, pd.Series]:
    if atr is None:
        previous_close = close.shift(1)
        tr = pd.concat(
            [high - low, (high - previous_close).abs(), (low - previous_close).abs()],
            axis=1,
        ).max(axis=1, skipna=False)
        atr = _technical_smooth(tr, period, 1 / period)
    result = {key: np.full(len(close), np.nan) for key in ("up", "down", "direction", "line")}
    final_upper, final_lower, previous_close = math.nan, math.nan, math.nan
    direction = 0
    for index, (h, l, c, volatility) in enumerate(zip(high, low, close, atr)):
        middle = h / 2 + l / 2
        upper, lower = middle + mult * volatility, middle - mult * volatility
        if not all(math.isfinite(value) for value in (upper, lower, c)):
            direction = 0
            continue
        if direction == 0:
            final_upper, final_lower, direction = upper, lower, 1
        else:
            final_upper = upper if upper < final_upper or previous_close > final_upper else final_upper
            final_lower = lower if lower > final_lower or previous_close < final_lower else final_lower
            if direction == 1 and c < final_lower:
                direction = -1
            elif direction == -1 and c > final_upper:
                direction = 1
        line = final_lower if direction == 1 else final_upper
        result["up" if direction == 1 else "down"][index] = line
        result["direction"][index] = direction
        result["line"][index] = line
        previous_close = c
    return {key: pd.Series(data) for key, data in result.items()}


def _technical_obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    result = np.full(len(close), np.nan)
    previous, total = math.nan, 0.0
    for index, (c, v) in enumerate(zip(close, volume)):
        if not math.isfinite(c) or not math.isfinite(v):
            previous, total = math.nan, 0.0
            continue
        if math.isfinite(previous):
            total += v if c > previous else -v if c < previous else 0.0
        else:
            total = 0.0  # Each uninterrupted close/volume segment restarts OBV at zero.
        if math.isfinite(total):
            result[index] = total
            previous = c
        else:
            previous, total = math.nan, 0.0
    return pd.Series(result)


def indicator_series(bars: list[dict[str, Any]],
                     params: dict[str, Any] | None = None) -> dict[str, Any]:
    effective = normalize_indicator_params(params)
    # No explicit params keeps the historical MA set, including ma10, for API compatibility.
    ma_periods = (5, 10, 20, 50, 200) if params is None else effective["ma_periods"]
    close = _technical_values([bar.get("c") for bar in bars])
    high = _technical_values([bar.get("h") for bar in bars])
    low = _technical_values([bar.get("l") for bar in bars])
    volume = _technical_values([bar.get("v") for bar in bars])
    volume = volume.where(volume >= 0)
    valid_hlc = close.notna() & high.notna() & low.notna() & (high >= low)
    high, low, hlc_close = high.where(valid_hlc), low.where(valid_hlc), close.where(valid_hlc)
    indicators: dict[str, Any] = {
        f"ma{period}": close.rolling(period, min_periods=period).mean()
        for period in ma_periods
    }
    for period in (5, 20):
        indicators[f"vol_ma{period}"] = volume.rolling(period, min_periods=period).mean()

    dif = (_technical_smooth(close, effective["macd_fast"], 2 / (effective["macd_fast"] + 1))
           - _technical_smooth(close, effective["macd_slow"], 2 / (effective["macd_slow"] + 1)))
    dea = _technical_smooth(dif, effective["macd_signal"], 2 / (effective["macd_signal"] + 1))
    indicators["macd"] = {"dif": dif, "dea": dea, "hist": 2 * (dif - dea)}
    indicators[f"rsi{effective['rsi_period']}"] = _rsi_series(close.tolist(), effective["rsi_period"])

    bb_mid = close.rolling(effective["bb_period"], min_periods=effective["bb_period"]).mean()
    deviation = close.rolling(effective["bb_period"], min_periods=effective["bb_period"]).std(ddof=0)
    bb_upper = bb_mid + effective["bb_mult"] * deviation
    bb_lower = bb_mid - effective["bb_mult"] * deviation
    bb_range = bb_upper - bb_lower
    indicators["bb"] = {
        "mid": bb_mid, "upper": bb_upper, "lower": bb_lower,
        "width": bb_range / bb_mid.where(bb_mid != 0) * 100,
        "percent_b": (close - bb_lower) / bb_range.where(bb_range != 0),
    }

    previous_close = hlc_close.shift(1)
    tr = pd.concat([high - low, (high - previous_close).abs(), (low - previous_close).abs()], axis=1).max(axis=1, skipna=False)
    # ATR/DM seeds use n actual transitions (bars 1..n); the first ADX reading is bar 2*period-1.
    kc_period = effective["kc_period"]
    kc_mid = _technical_smooth(hlc_close, kc_period, 2 / (kc_period + 1))
    kc_atr = _technical_smooth(tr, effective["kc_atr_period"], 1 / effective["kc_atr_period"])
    indicators["kc"] = {
        "mid": kc_mid,
        "upper": kc_mid + effective["kc_mult"] * kc_atr,
        "lower": kc_mid - effective["kc_mult"] * kc_atr,
    }
    atr = _technical_smooth(tr, effective["atr_period"], 1 / effective["atr_period"])
    indicators[f"atr{effective['atr_period']}"] = atr
    indicators["atr_pct"] = atr / close.where(close != 0) * 100

    period = effective["donchian_period"]
    hh = high.rolling(period, min_periods=period).max()
    ll = low.rolling(period, min_periods=period).min()
    dc_upper, dc_lower = hh.shift(1).where(valid_hlc), ll.shift(1).where(valid_hlc)
    indicators["donchian"] = {"mid": (dc_upper + dc_lower) / 2, "upper": dc_upper, "lower": dc_lower}
    indicators["regression"] = _technical_ols(close, effective["regression_period"], effective["regression_mult"])
    typical = high / 3 + low / 3 + hlc_close / 3
    indicators["vwap"] = _technical_vwap(typical, volume, effective["vwap_period"], effective["vwap_mult"])

    period = effective["kama_period"]
    kama, er = _technical_kama(close, period, effective["kama_fast"], effective["kama_slow"])
    indicators[f"kama{period}"], indicators[f"er{period}"] = kama, er
    adaptive_kama, adaptive_er = _technical_kama(
        close, effective["adaptive_period"], effective["adaptive_fast"], effective["adaptive_slow"]
    )
    adaptive_atr = _technical_smooth(
        tr, effective["adaptive_atr_period"], 1 / effective["adaptive_atr_period"]
    )
    adaptive_width = adaptive_atr * (effective["adaptive_mult"] + adaptive_er)
    indicators["adaptive"] = {
        "mid": adaptive_kama,
        "upper": adaptive_kama + adaptive_width,
        "lower": adaptive_kama - adaptive_width,
        "er": adaptive_er,
    }
    st_atr = _technical_smooth(
        tr, effective["supertrend_period"], 1 / effective["supertrend_period"]
    )
    indicators["supertrend"] = _technical_supertrend(
        high, low, hlc_close, st_atr,
        period=effective["supertrend_period"], mult=effective["supertrend_mult"],
    )

    adx_period = effective["adx_period"]
    adx_atr = _technical_smooth(tr, adx_period, 1 / adx_period)
    up, down = high.diff(), -low.diff()
    valid_pair = valid_hlc & valid_hlc.shift(1, fill_value=False)
    plus_dm = up.where((up > down) & (up > 0), 0.0).where(valid_pair)
    minus_dm = down.where((down > up) & (down > 0), 0.0).where(valid_pair)
    plus = (_technical_smooth(plus_dm, adx_period, 1 / adx_period)
            / adx_atr.where(adx_atr != 0) * 100).mask(adx_atr == 0, 0.0)
    minus = (_technical_smooth(minus_dm, adx_period, 1 / adx_period)
             / adx_atr.where(adx_atr != 0) * 100).mask(adx_atr == 0, 0.0)
    di_sum = plus + minus
    dx = ((plus - minus).abs() / di_sum.where(di_sum != 0) * 100).mask(di_sum == 0, 0.0)
    indicators["adx"] = {
        "adx": _technical_smooth(dx, adx_period, 1 / adx_period),
        "plus_di": plus,
        "minus_di": minus,
    }

    stoch_period = effective["stoch_period"]
    hh = high.rolling(stoch_period, min_periods=stoch_period).max()
    ll = low.rolling(stoch_period, min_periods=stoch_period).min()
    span = hh - ll
    raw_k = (hlc_close - ll) / span.where(span != 0) * 100
    slow_k = raw_k.rolling(effective["stoch_k"], min_periods=effective["stoch_k"]).mean()
    indicators["stochastic"] = {
        "k": slow_k,
        "d": slow_k.rolling(effective["stoch_d"], min_periods=effective["stoch_d"]).mean(),
    }

    spread = high - low
    multiplier = ((2 * hlc_close - high - low) / spread.where(spread != 0)).mask(spread == 0, 0.0)
    cmf_volume = volume.where(valid_hlc)
    cmf_period = effective["cmf_period"]
    volume_sum = cmf_volume.rolling(cmf_period, min_periods=cmf_period).sum()
    indicators[f"cmf{cmf_period}"] = (
        (multiplier * cmf_volume).rolling(cmf_period, min_periods=cmf_period).sum()
        / volume_sum.where(volume_sum > 0)
    )
    indicators["obv"] = _technical_obv(close, volume)

    squeeze_bb_period = effective["squeeze_bb_period"]
    squeeze_bb_mid = close.rolling(squeeze_bb_period, min_periods=squeeze_bb_period).mean()
    squeeze_deviation = close.rolling(squeeze_bb_period, min_periods=squeeze_bb_period).std(ddof=0)
    squeeze_bb_upper = squeeze_bb_mid + effective["squeeze_bb_mult"] * squeeze_deviation
    squeeze_bb_lower = squeeze_bb_mid - effective["squeeze_bb_mult"] * squeeze_deviation
    squeeze_kc_period = effective["squeeze_kc_period"]
    squeeze_kc_mid = _technical_smooth(
        hlc_close, squeeze_kc_period, 2 / (squeeze_kc_period + 1)
    )
    squeeze_atr = _technical_smooth(tr, squeeze_kc_period, 1 / squeeze_kc_period)
    squeeze_upper = squeeze_kc_mid + effective["squeeze_kc_mult"] * squeeze_atr
    squeeze_lower = squeeze_kc_mid - effective["squeeze_kc_mult"] * squeeze_atr
    ready = (np.isfinite(squeeze_bb_upper) & np.isfinite(squeeze_bb_lower)
             & np.isfinite(squeeze_upper) & np.isfinite(squeeze_lower))
    on = ((squeeze_bb_upper < squeeze_upper) & (squeeze_bb_lower > squeeze_lower)).astype(float).where(ready)
    momentum_period = effective["squeeze_momentum_period"]
    squeeze_hh = high.rolling(momentum_period, min_periods=momentum_period).max()
    squeeze_ll = low.rolling(momentum_period, min_periods=momentum_period).min()
    centered_close = hlc_close - ((squeeze_hh + squeeze_ll) / 2 + squeeze_bb_mid) / 2
    indicators["squeeze"] = {
        "on": on,
        "momentum": _technical_ols(centered_close, momentum_period)["mid"],
    }
    return _technical_export(indicators)


def _technical_snapshot(bars: list[dict[str, Any]], quote: dict[str, Any]) -> dict[str, Any]:
    closes = [float(bar["c"]) for bar in bars if bar.get("c") is not None]
    if not closes:
        return {
            "rsi": None,
            "ma20": None,
            "ma50": None,
            "ma200": None,
            "ret_1m": None,
            "ret_3m": None,
            "ret_ytd": None,
            "from_high": None,
        }
    last = closes[-1]
    year = datetime.now().year
    ytd_prices = [
        float(bar["c"])
        for bar in bars
        if bar.get("c") is not None and str(bar.get("t", "")).startswith(str(year))
    ]
    window = closes[-252:]
    high = max(window) if window else None
    quote_high = quote.get("week52_high")
    if quote_high:
        high = max(high or 0, float(quote_high))
    return {
        "rsi": round(rsi(closes), 1) if rsi(closes) is not None else None,
        "ma20": round(sma(closes, 20), 2) if sma(closes, 20) else None,
        "ma50": round(sma(closes, 50), 2) if sma(closes, 50) else None,
        "ma200": round(sma(closes, 200), 2) if sma(closes, 200) else None,
        "ret_1m": round((last / closes[-22] - 1) * 100, 2) if len(closes) > 22 else None,
        "ret_3m": round((last / closes[-64] - 1) * 100, 2) if len(closes) > 64 else None,
        "ret_ytd": round((last / ytd_prices[0] - 1) * 100, 2) if len(ytd_prices) > 1 else None,
        "from_high": round((last / high - 1) * 100, 2) if high else None,
        "last": round(last, 4),
    }


def pick_peers(
    universe_items: list[dict[str, Any]],
    industry: str | None,
    exclude_symbol: str,
    limit: int = 8,
) -> list[dict[str, Any]]:
    if not industry:
        return []
    peers = [
        item
        for item in universe_items
        if not item.get("is_etf")
        and item.get("industry") == industry
        and item.get("symbol") != exclude_symbol
        and (item.get("market_cap") or 0) > 3e8
    ]
    peers.sort(key=lambda item: item.get("market_cap") or 0, reverse=True)
    return peers[:limit]


def score_stock(
    quote: dict[str, Any],
    financials: dict[str, Any],
    bars: list[dict[str, Any]],
    universe_items: list[dict[str, Any]],
    dividend: dict[str, Any] | None = None,
) -> dict[str, Any]:
    annual = financials.get("annual") or []
    quarterly = financials.get("quarterly") or []
    latest_annual = annual[0] if annual else (quarterly[0] if quarterly else {})
    latest_quarter = quarterly[0] if quarterly else latest_annual
    industry = quote.get("industry") or ""
    peers = pick_peers(universe_items, industry, quote.get("symbol", ""), limit=60)

    pe = quote.get("pe")
    pb = quote.get("pb")
    eps = quote.get("eps_ttm")
    if pe is None and eps not in (None, 0) and quote.get("price"):
        pe = round(float(quote["price"]) / float(eps), 2)
    if dividend and dividend.get("yield_pct") and not quote.get("dividend_yield"):
        quote["dividend_yield"] = dividend["yield_pct"]

    sector_pe_values = [
        float(item["pe"]) for item in peers if item.get("pe") is not None and 0 < item["pe"] < 500
    ]
    sector_pb_values = [
        float(item["pb"]) for item in peers if item.get("pb") is not None and 0 < item["pb"] < 100
    ]
    sector_pe = _median(sector_pe_values)
    sector_pb = _median(sector_pb_values)

    pe_pct = _percentile_rank(float(pe) if pe is not None and pe > 0 else None, sector_pe_values)
    pb_pct = _percentile_rank(float(pb) if pb is not None and pb > 0 else None, sector_pb_values)
    valuation_parts = []
    valuation_detail = []
    if pe_pct is not None:
        valuation_parts.append(100 - pe_pct)
        valuation_detail.append(f"PE {pe:.1f}x，行业 {pe_pct:.0f}% 分位")
    if pb_pct is not None:
        valuation_parts.append(100 - pb_pct)
        valuation_detail.append(f"PB {pb:.1f}x，行业 {pb_pct:.0f}% 分位")
    valuation_score = float(np.mean(valuation_parts)) if valuation_parts else 55.0
    if pe is not None and pe < 0:
        valuation_score = min(valuation_score, 25)
        valuation_detail.append("公司当前亏损，PE 不适用")
    if not valuation_detail:
        valuation_detail.append("行业估值样本不足，按中性处理")

    revenue_yoy = latest_quarter.get("revenue_yoy")
    profit_yoy = latest_quarter.get("net_profit_yoy")
    growth_parts = [
        part
        for part in (
            _interp([(-25, 8), (-10, 25), (0, 42), (10, 63), (25, 82), (50, 95)], revenue_yoy),
            _interp([(-40, 5), (-20, 22), (0, 45), (15, 68), (35, 86), (80, 96)], profit_yoy),
        )
        if part is not None
    ]
    growth_score = float(np.mean(growth_parts)) if growth_parts else 50.0
    if (latest_quarter.get("net_profit") or 0) < 0:
        growth_score = min(growth_score, 40)
    growth_detail = []
    if revenue_yoy is not None:
        growth_detail.append(f"营收同比 {revenue_yoy:+.1f}%")
    if profit_yoy is not None:
        growth_detail.append(f"净利同比 {profit_yoy:+.1f}%")
    if not growth_detail:
        growth_detail.append("暂无最新增速数据")

    profitability_parts = [
        part
        for part in (
            _interp([(0, 12), (20, 35), (40, 60), (60, 80), (80, 92)], latest_annual.get("gross_margin")),
            _interp([(0, 10), (5, 35), (10, 55), (20, 75), (30, 88), (45, 95)], latest_annual.get("net_margin")),
            _interp([(0, 15), (5, 35), (10, 50), (15, 68), (25, 85), (40, 95)], latest_annual.get("roe")),
        )
        if part is not None
    ]
    profitability_score = float(np.mean(profitability_parts)) if profitability_parts else 50.0
    profitability_detail = []
    if latest_annual.get("gross_margin") is not None:
        profitability_detail.append(f"毛利率 {latest_annual['gross_margin']:.1f}%")
    if latest_annual.get("net_margin") is not None:
        profitability_detail.append(f"净利率 {latest_annual['net_margin']:.1f}%")
    if latest_annual.get("roe") is not None:
        profitability_detail.append(f"ROE {latest_annual['roe']:.1f}%")
    if not profitability_detail:
        profitability_detail.append("暂无利润率数据")

    is_financial = any(keyword in industry for keyword in ("金融", "银行", "保险"))
    health_parts = []
    if is_financial:
        health_score = 52.0
        health_detail = "金融行业负债结构特殊，健康度按中性处理"
    else:
        debt_score = _interp([(0, 92), (20, 86), (40, 70), (60, 50), (80, 25), (100, 8)], latest_annual.get("debt_ratio"))
        current_score = _interp([(0.5, 20), (1.0, 45), (1.5, 65), (2.0, 80), (3.0, 90)], latest_annual.get("current_ratio"))
        health_parts = [part for part in (debt_score, current_score) if part is not None]
        health_score = float(np.mean(health_parts)) if health_parts else 55.0
        if (latest_annual.get("ocf_to_debt") or 0) > 0.2:
            health_score = min(100, health_score + 4)
        health_detail = []
        if latest_annual.get("debt_ratio") is not None:
            health_detail.append(f"负债率 {latest_annual['debt_ratio']:.1f}%")
        if latest_annual.get("current_ratio") is not None:
            health_detail.append(f"流动比率 {latest_annual['current_ratio']:.2f}")
        if not health_detail:
            health_detail.append("暂无资产负债表数据")

    technical = _technical_snapshot(bars, quote)
    momentum_parts = [
        part
        for part in (
            _interp([(-15, 10), (0, 50), (10, 78), (25, 92)], technical.get("ret_1m")),
            _interp([(-25, 10), (0, 50), (20, 82), (50, 95)], technical.get("ret_3m")),
            _interp([(-30, 10), (0, 50), (30, 85), (80, 97)], technical.get("ret_ytd")),
        )
        if part is not None
    ]
    momentum_score = float(np.mean(momentum_parts)) if momentum_parts else 50.0
    compare_mode = 0
    if technical.get("ma20") and technical.get("last"):
        compare_mode += 3 if technical["last"] > technical["ma20"] else -3
    if technical.get("ma50") and technical.get("last"):
        compare_mode += 3 if technical["last"] > technical["ma50"] else -3
    if technical.get("ma200") and technical.get("last"):
        compare_mode += 4 if technical["last"] > technical["ma200"] else -5
    momentum_score = _clamp(momentum_score + compare_mode)
    momentum_detail = []
    if technical.get("ret_1m") is not None:
        momentum_detail.append(f"近1月 {technical['ret_1m']:+.1f}%")
    if technical.get("ret_3m") is not None:
        momentum_detail.append(f"近3月 {technical['ret_3m']:+.1f}%")
    if technical.get("ret_ytd") is not None:
        momentum_detail.append(f"年初至今 {technical['ret_ytd']:+.1f}%")
    if not momentum_detail:
        momentum_detail.append("行情样本不足")

    factors_raw = [
        ("valuation", "估值", valuation_score, 0.20, "；".join(valuation_detail)),
        ("growth", "成长", growth_score, 0.20, "；".join(growth_detail)),
        ("profitability", "盈利", profitability_score, 0.20, "；".join(profitability_detail)),
        ("health", "财务健康", health_score, 0.15, "；".join(health_detail)),
        ("momentum", "动量", momentum_score, 0.25, "；".join(momentum_detail)),
    ]
    weight_total = sum(item[3] for item in factors_raw)
    total = sum(item[2] * item[3] for item in factors_raw) / weight_total if weight_total else 50
    total = round(_clamp(total), 1)

    if total >= 78:
        verdict, verdict_tone = "积极关注", "positive"
    elif total >= 65:
        verdict, verdict_tone = "中性偏多", "positive"
    elif total >= 50:
        verdict, verdict_tone = "中性观察", "neutral"
    elif total >= 35:
        verdict, verdict_tone = "偏谨慎", "caution"
    else:
        verdict, verdict_tone = "风险较高", "danger"

    reasons = []
    if pe_pct is not None:
        if pe_pct <= 35:
            reasons.append(f"估值相对行业偏低：PE {pe:.1f}x，处于行业 {pe_pct:.0f}% 分位。")
        elif pe_pct >= 70:
            reasons.append(f"估值高于行业多数公司：PE {pe:.1f}x，处于行业 {pe_pct:.0f}% 分位。")
        else:
            reasons.append(f"估值处于行业中段：PE {pe:.1f}x，行业 {pe_pct:.0f}% 分位。")
    if revenue_yoy is not None:
        reasons.append(
            f"最近季度营收同比 {revenue_yoy:+.1f}%"
            + ("，增长动能较强。" if revenue_yoy >= 10 else "，增长较为平稳。" if revenue_yoy >= 0 else "，收入端承压。")
        )
    if latest_annual.get("net_margin") is not None and latest_annual.get("gross_margin") is not None:
        reasons.append(
            f"盈利质量：毛利率 {latest_annual['gross_margin']:.1f}%、净利率 {latest_annual['net_margin']:.1f}%。"
        )
    if not is_financial and latest_annual.get("debt_ratio") is not None:
        reasons.append(
            f"资产负债率 {latest_annual['debt_ratio']:.1f}%"
            + ("，杠杆水平偏高。" if latest_annual["debt_ratio"] >= 70 else "，财务结构相对稳健。")
        )
    if technical.get("ret_3m") is not None:
        reasons.append(
            f"近 3 个月股价 {technical['ret_3m']:+.1f}%"
            + ("，趋势偏强。" if technical["ret_3m"] > 5 else "，趋势偏弱。" if technical["ret_3m"] < -5 else "，横盘震荡。")
        )
    reasons = reasons[:5]

    risks = []
    if pe is not None and pe < 0:
        risks.append("公司当前处于亏损状态，市盈率不具参考意义。")
    if not is_financial and (latest_annual.get("debt_ratio") or 0) >= 80:
        risks.append(f"资产负债率 {latest_annual['debt_ratio']:.1f}%，偿债压力需要关注。")
    if (latest_annual.get("current_ratio") or 99) < 1:
        risks.append(f"流动比率 {latest_annual['current_ratio']:.2f}，短期流动性偏紧。")
    if (revenue_yoy or 0) < 0:
        risks.append("最新季度营收同比下滑，需跟踪需求变化。")
    if (profit_yoy or 0) < -20:
        risks.append("净利润同比大幅下滑，盈利端存在压力。")
    if technical.get("rsi") and technical["rsi"] > 75:
        risks.append(f"RSI {technical['rsi']:.0f}，短线超买。")
    if technical.get("rsi") and technical["rsi"] < 25:
        risks.append(f"RSI {technical['rsi']:.0f}，短线超卖。")
    if (technical.get("from_high") or 0) <= -30:
        risks.append(f"较 52 周高点回撤 {abs(technical['from_high']):.0f}%。")
    if technical.get("ma200") and technical.get("last") and technical["last"] < technical["ma200"]:
        risks.append("股价位于 200 日均线下方，中期趋势偏弱。")
    if not risks:
        risks.append("暂未发现显著的财务或技术面风险信号。")

    factors = [
        {
            "key": key,
            "label": label,
            "score": round(float(score), 1),
            "weight": weight,
            "detail": detail,
        }
        for key, label, score, weight, detail in factors_raw
    ]

    return {
        "total": total,
        "verdict": verdict,
        "verdict_tone": verdict_tone,
        "factors": factors,
        "reasons": reasons,
        "risks": risks,
        "metrics": {
            "pe": round(pe, 2) if pe is not None else None,
            "pb": round(pb, 2) if pb is not None else None,
            "sector_pe": round(sector_pe, 2) if sector_pe else None,
            "sector_pb": round(sector_pb, 2) if sector_pb else None,
            "pe_percentile": round(pe_pct, 1) if pe_pct is not None else None,
            "pb_percentile": round(pb_pct, 1) if pb_pct is not None else None,
            "dividend_yield": quote.get("dividend_yield"),
            "eps_ttm": quote.get("eps_ttm"),
            "industry": industry,
            "peer_count": len(peers),
        },
        "technical": technical,
        "as_of": latest_quarter.get("date") or latest_annual.get("date"),
        "disclaimer": "评分由公开财务与行情数据按固定规则计算，仅供研究参考，不构成投资建议。",
    }


def _series_metrics(returns: pd.Series, bench_returns: pd.Series | None = None) -> dict[str, Any]:
    clean = returns.dropna()
    if len(clean) < 10:
        return {
            "total_return": None,
            "annual_return": None,
            "volatility": None,
            "sharpe": None,
            "sortino": None,
            "max_drawdown": None,
            "var_95": None,
            "cvar_95": None,
            "beta": None,
            "correlation": None,
        }
    cumulative = (1 + clean).cumprod()
    total_return = cumulative.iloc[-1] - 1
    n = len(clean)
    annual_return = (1 + total_return) ** (252 / n) - 1
    volatility = clean.std(ddof=1) * math.sqrt(252)
    sharpe = (annual_return - RISK_FREE) / volatility if volatility else None
    downside = clean[clean < 0]
    downside_vol = downside.std(ddof=1) * math.sqrt(252) if len(downside) > 1 else None
    sortino = (annual_return - RISK_FREE) / downside_vol if downside_vol else None
    drawdown = cumulative / cumulative.cummax() - 1
    max_drawdown = float(drawdown.min())
    var_threshold = float(np.percentile(clean, 5))
    var_95 = -var_threshold
    tail = clean[clean <= var_threshold]
    cvar_95 = float(-tail.mean()) if len(tail) else None
    beta = None
    correlation = None
    if bench_returns is not None:
        joined = pd.concat([clean, bench_returns], axis=1, join="inner").dropna()
        if len(joined) > 10:
            covariance = joined.iloc[:, 0].cov(joined.iloc[:, 1])
            variance = joined.iloc[:, 1].var()
            beta = float(covariance / variance) if variance else None
            correlation = float(joined.iloc[:, 0].corr(joined.iloc[:, 1]))
    return {
        "total_return": round(float(total_return) * 100, 2),
        "annual_return": round(float(annual_return) * 100, 2),
        "volatility": round(float(volatility) * 100, 2),
        "sharpe": round(float(sharpe), 2) if sharpe is not None else None,
        "sortino": round(float(sortino), 2) if sortino is not None else None,
        "max_drawdown": round(float(max_drawdown) * 100, 2),
        "var_95": round(var_95 * 100, 2),
        "cvar_95": round(cvar_95 * 100, 2) if cvar_95 is not None else None,
        "beta": round(beta, 2) if beta is not None else None,
        "correlation": round(correlation, 2) if correlation is not None else None,
    }


def _downsample_series(dates: list[str], series: dict[str, list[float]], max_points: int = 280) -> dict[str, Any]:
    length = len(dates)
    if length <= max_points:
        return {"dates": dates, "series": series}
    step = max(1, length // max_points)
    indices = list(range(0, length, step))
    if indices[-1] != length - 1:
        indices.append(length - 1)
    return {
        "dates": [dates[index] for index in indices],
        "series": {key: [values[index] for index in indices] for key, values in series.items()},
    }


def compare(
    entries: list[dict[str, Any]],
    benchmark_bars: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    closes = {}
    names = {}
    for entry in entries:
        bars = entry.get("bars") or []
        if not bars:
            continue
        series_data = {}
        for bar in bars:
            if bar.get("c") is not None:
                series_data[str(bar["t"])] = float(bar["c"])
        if len(series_data) < 5:
            continue
        closes[entry["symbol"]] = pd.Series(series_data)
        names[entry["symbol"]] = entry.get("name") or entry["symbol"]
    if not closes:
        return {
            "symbols": [],
            "performance": {"dates": [], "series": {}},
            "drawdown": {"dates": [], "series": {}},
            "metrics": [],
            "correlation": [],
        }

    frame = pd.concat(closes, axis=1, join="inner").dropna().sort_index()
    if len(frame) < 5:
        return {
            "symbols": [],
            "performance": {"dates": [], "series": {}},
            "drawdown": {"dates": [], "series": {}},
            "metrics": [],
            "correlation": [],
        }
    normalized = frame / frame.iloc[0] * 100
    returns = frame.pct_change().dropna()
    bench_returns = None
    bench_series = None
    if benchmark_bars:
        bench_series = pd.Series({str(bar["t"]): float(bar["c"]) for bar in benchmark_bars if bar.get("c") is not None})
        bench_series = bench_series.reindex(frame.index).ffill()
        bench_returns = bench_series.pct_change().dropna()

    metrics = []
    for symbol in frame.columns:
        item_metrics = _series_metrics(returns[symbol], bench_returns)
        item_metrics.update({"symbol": symbol, "name": names.get(symbol, symbol)})
        metrics.append(item_metrics)

    corr = returns.corr().round(3)
    correlation = {
        "symbols": [str(item) for item in corr.columns],
        "matrix": [[None if pd.isna(value) else float(value) for value in row] for row in corr.values],
    }
    dates = [str(index) for index in normalized.index]
    series = {str(symbol): [round(float(value), 2) for value in normalized[symbol].values] for symbol in normalized.columns}
    drawdown_series: dict[str, list[float | None]] = {}
    for symbol in normalized.columns:
        values = normalized[symbol]
        peaks = values.cummax()
        drawdown_series[str(symbol)] = [
            None if pd.isna(value) or pd.isna(peak) else round(float((value / peak - 1) * 100), 2) if peak else 0.0
            for value, peak in zip(values.values, peaks.values)
        ]
    if bench_series is not None:
        valid = bench_series.dropna()
        if len(valid) >= 5:
            bench_normalized = bench_series / valid.iloc[0] * 100
            series["benchmark"] = [
                None if pd.isna(value) else round(float(value), 2) for value in bench_normalized.values
            ]
            bench_peaks = bench_normalized.cummax()
            drawdown_series["benchmark"] = [
                None if pd.isna(value) else round(float((value / peak - 1) * 100), 2) if peak else 0.0
                for value, peak in zip(bench_normalized.values, bench_peaks.values)
            ]
    performance = _downsample_series(dates, series)
    drawdown = _downsample_series(dates, drawdown_series)
    return {
        "symbols": [
            {"symbol": str(symbol), "name": names.get(str(symbol), str(symbol))} for symbol in frame.columns
        ],
        "performance": performance,
        "drawdown": drawdown,
        "metrics": metrics,
        "correlation": correlation,
        "benchmark": "SPY" if benchmark_bars else None,
    }


def _monthly_returns(dates: list[str], closes: pd.Series, years: int = 5) -> list[dict[str, Any]]:
    frame = pd.DataFrame({"d": dates, "c": closes.values}).dropna()
    if frame.empty:
        return []
    frame["d"] = pd.to_datetime(frame["d"], errors="coerce")
    frame = frame.dropna(subset=["d"]).set_index("d")["c"]
    monthly = frame.resample("ME").last().pct_change().dropna()
    start = pd.Timestamp.now().normalize() - pd.DateOffset(years=years)
    monthly = monthly[monthly.index >= start]
    return [
        {
            "month": stamp.strftime("%Y-%m"),
            "return": round(float(value) * 100, 2),
        }
        for stamp, value in monthly.items()
    ]


def risk_report(
    bars: list[dict[str, Any]],
    benchmark_bars: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """QuantStats 风格的风险面板：分位、回撤、滚动夏普、尾部与期限结构指标。"""
    clean = [bar for bar in bars or [] if _as_float(bar.get("c")) not in (None, 0)]
    if len(clean) < 40:
        return {}
    dates = [str(bar.get("t")) for bar in clean]
    closes = pd.Series([float(bar["c"]) for bar in clean], index=dates)
    returns = closes.pct_change().dropna()
    length = len(closes)

    def window(days: int) -> tuple[pd.Series, pd.Series] | None:
        if length < days:
            return None
        start = max(length - days, 0)
        series = closes.iloc[start:]
        if len(series) < 20:
            return None
        return dates[start:], series

    horizons: dict[str, Any] = {}
    bench_returns: pd.Series | None = None
    if benchmark_bars:
        bench = {
            str(bar.get("t")): _as_float(bar.get("c"))
            for bar in benchmark_bars
            if _as_float(bar.get("c"))
        }
        bench_returns = pd.Series(
            [bench.get(date) for date in returns.index], index=returns.index, dtype="float64"
        ).dropna()
        bench_returns = bench_returns.pct_change().dropna()
        if len(bench_returns) < 20:
            bench_returns = None

    for label, days in (("1Y", 252), ("3Y", 756), ("5Y", 1260)):
        frame = window(days)
        if frame is None:
            continue
        window_dates, series = frame
        window_returns = series.pct_change().dropna()
        metrics = _series_metrics(window_returns, bench_returns)
        peak = series.cummax()
        drawdown = series / peak - 1
        high = float(series.max())
        low = float(series.min())
        metrics["drawdown_now"] = round(float(drawdown.iloc[-1]) * 100, 2)
        metrics["from_high"] = round((float(series.iloc[-1]) / high - 1) * 100, 2)
        metrics["from_low"] = round((float(series.iloc[-1]) / low - 1) * 100, 2)
        metrics["percentile"] = round(float((series.iloc[-1] - low) / (high - low) * 100), 1) if high > low else None
        metrics["ulcer"] = round(float(np.sqrt((drawdown**2).mean())) * 100, 2)
        gains = float(window_returns[window_returns > 0].sum())
        losses = float(window_returns[window_returns < 0].sum())
        metrics["tail_ratio"] = round(gains / abs(losses), 2) if losses else None
        metrics["up_days"] = round(float((window_returns > 0).mean() * 100), 1)
        metrics["best_day"] = round(float(window_returns.max()) * 100, 2)
        metrics["worst_day"] = round(float(window_returns.min()) * 100, 2)
        metrics["skew"] = round(float(window_returns.skew()), 2) if len(window_returns) > 3 else None
        metrics["kurtosis"] = round(float(window_returns.kurtosis()), 2) if len(window_returns) > 3 else None
        downside = window_returns[window_returns < 0]
        upside = window_returns[window_returns > 0]
        if bench_returns is not None:
            joined = pd.concat([window_returns, bench_returns], axis=1, join="inner").dropna()
            if len(joined) > 20:
                asset, bench = joined.iloc[:, 0], joined.iloc[:, 1]
                positive = bench > 0
                negative = bench < 0
                metrics["up_capture"] = (
                    round(float(asset[positive].mean() / bench[positive].mean() * 100), 1)
                    if positive.any() and bench[positive].mean()
                    else None
                )
                metrics["down_capture"] = (
                    round(float(asset[negative].mean() / bench[negative].mean() * 100), 1)
                    if negative.any() and bench[negative].mean()
                    else None
                )
                downside_asset = asset[asset < 0]
                downside_bench = bench[bench < 0]
                if len(downside_asset) > 5 and len(downside_bench) > 5:
                    variance = float(downside_bench.var())
                    metrics["downside_beta"] = (
                        round(float(downside_asset.cov(downside_bench) / variance), 2) if variance else None
                    )
                sharpe_series = window_returns.rolling(63).mean() * 252
                vol_series = window_returns.rolling(63).std() * math.sqrt(252)
                rolling = (sharpe_series - RISK_FREE) / vol_series
                rolling = rolling.replace([np.inf, -np.inf], np.nan)
                metrics["rolling_sharpe"] = [
                    {"date": stamp, "value": round(float(value), 2)}
                    for stamp, value in rolling.dropna().items()
                ][-60:]
        horizons[label] = metrics

    moving = {period: sma(list(closes.values), period) for period in (20, 50, 200)}
    last = float(closes.iloc[-1])
    trend = {
        "ma20": round(moving[20], 2) if moving[20] else None,
        "ma50": round(moving[50], 2) if moving[50] else None,
        "ma200": round(moving[200], 2) if moving[200] else None,
        "above_ma50": bool(moving[50] and last >= moving[50]),
        "above_ma200": bool(moving[200] and last >= moving[200]),
        "ma50_spread": round((last / moving[50] - 1) * 100, 2) if moving[50] else None,
        "ma200_spread": round((last / moving[200] - 1) * 100, 2) if moving[200] else None,
    }
    if moving[50] and moving[200]:
        trend["regime"] = "多头排列" if moving[50] >= moving[200] else "空头排列"

    peak = closes.cummax()
    drawdown = (closes / peak - 1) * 100
    streak = 0
    worst_streak = 0
    for value in drawdown:
        if value < -0.01:
            streak += 1
            worst_streak = max(worst_streak, streak)
        else:
            streak = 0
    trough_index = int(drawdown.values.argmin())
    recovery = None
    if trough_index < length - 1:
        recovery = length - 1 - trough_index
    return {
        "as_of": dates[-1],
        "bars": length,
        "horizons": horizons,
        "trend": trend,
        "drawdown": {
            "max": round(float(drawdown.min()), 2),
            "now": round(float(drawdown.iloc[-1]), 2),
            "trough_date": dates[trough_index],
            "recovery_days": recovery,
            "longest_under_water": worst_streak,
            "series": [
                {"date": date, "value": round(float(value), 2)}
                for date, value in list(zip(dates, drawdown))[-260:]
            ],
        },
        "monthly": _monthly_returns(dates, closes),
    }


def _as_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def analyze_portfolio(
    transactions: list[dict[str, Any]],
    quotes_map: dict[str, dict[str, Any]],
    bars_map: dict[str, list[dict[str, Any]]],
    benchmark_bars: list[dict[str, Any]] | None = None,
    sector_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    sector_map = sector_map or {}
    state: dict[str, dict[str, Any]] = {}
    invested_total = 0.0
    warnings: list[str] = []
    for tx in sorted(transactions, key=lambda item: str(item.get("date") or "")):
        symbol = str(tx.get("symbol") or "").upper()
        side = str(tx.get("side") or "buy").lower()
        shares = _as_float(tx.get("shares")) or 0
        price = _as_float(tx.get("price")) or 0
        fee = _as_float(tx.get("fee")) or 0
        if not symbol or shares <= 0 or price <= 0:
            warnings.append("存在无效交易记录，已跳过。")
            continue
        holding = state.setdefault(
            symbol,
            {"qty": 0.0, "cost": 0.0, "realized": 0.0, "name": tx.get("name") or symbol},
        )
        if side == "sell":
            if holding["qty"] <= 0:
                warnings.append(f"{symbol} 的卖出记录没有可匹配的持仓，已跳过。")
                continue
            sell_qty = min(shares, holding["qty"])
            if sell_qty < shares:
                warnings.append(f"{symbol} 的卖出数量超过持仓，按 {sell_qty:.4f} 股计算。")
            average_cost = holding["cost"] / holding["qty"] if holding["qty"] else 0
            cost_removed = average_cost * sell_qty
            proceeds = sell_qty * price - fee
            holding["realized"] += proceeds - cost_removed
            holding["qty"] -= sell_qty
            holding["cost"] -= cost_removed
            if holding["qty"] <= 1e-8:
                holding["qty"] = 0.0
                holding["cost"] = 0.0
        else:
            cost = shares * price + fee
            holding["qty"] += shares
            holding["cost"] += cost
            invested_total += cost

    active = {symbol: holding for symbol, holding in state.items() if holding["qty"] > 1e-8}
    if not active:
        return {
            "empty": True,
            "summary": {
                "market_value": 0,
                "cost": 0,
                "unrealized": 0,
                "realized": round(sum(item["realized"] for item in state.values()), 2),
                "total_pnl": 0,
                "total_return_pct": 0,
                "day_pnl": 0,
                "day_pnl_pct": 0,
            },
            "positions": [],
            "allocation": {"holdings": [], "sectors": []},
            "performance": {"dates": [], "portfolio": [], "benchmark": []},
            "risk": {},
            "warnings": warnings,
        }

    positions = []
    market_value_total = 0.0
    day_pnl_total = 0.0
    sector_values: dict[str, float] = {}
    for symbol, holding in active.items():
        quote_data = quotes_map.get(symbol) or {}
        bars = bars_map.get(symbol) or []
        last = quote_data.get("price")
        if last is None and bars:
            last = bars[-1].get("c")
        last = float(last or 0)
        previous = quote_data.get("prev_close")
        if previous is None and len(bars) > 1:
            previous = bars[-2].get("c")
        market_value = holding["qty"] * last
        average_cost = holding["cost"] / holding["qty"] if holding["qty"] else 0
        unrealized = market_value - holding["cost"]
        day_pnl = (last - float(previous or last)) * holding["qty"]
        market_value_total += market_value
        day_pnl_total += day_pnl
        sector = sector_map.get(symbol) or quote_data.get("industry") or "其他"
        sector_values[sector] = sector_values.get(sector, 0) + market_value
        positions.append(
            {
                "symbol": symbol,
                "name": quote_data.get("name") or holding["name"] or symbol,
                "sector": sector,
                "qty": round(holding["qty"], 4),
                "avg_cost": round(average_cost, 4),
                "cost": round(holding["cost"], 2),
                "last": round(last, 4),
                "market_value": round(market_value, 2),
                "unrealized": round(unrealized, 2),
                "unrealized_pct": round(unrealized / holding["cost"] * 100, 2) if holding["cost"] else None,
                "realized": round(holding["realized"], 2),
                "day_pnl": round(day_pnl, 2),
                "day_pnl_pct": round((last / float(previous) - 1) * 100, 2) if previous else None,
            }
        )
    for position in positions:
        position["weight"] = round(position["market_value"] / market_value_total * 100, 2) if market_value_total else 0
    positions.sort(key=lambda item: item["market_value"], reverse=True)

    cost_total = sum(holding["cost"] for holding in active.values())
    realized_total = sum(item["realized"] for item in state.values())
    unrealized_total = market_value_total - cost_total
    total_pnl = unrealized_total + realized_total
    total_return_pct = total_pnl / invested_total * 100 if invested_total else 0
    summary = {
        "market_value": round(market_value_total, 2),
        "cost": round(cost_total, 2),
        "unrealized": round(unrealized_total, 2),
        "realized": round(realized_total, 2),
        "total_pnl": round(total_pnl, 2),
        "total_return_pct": round(total_return_pct, 2),
        "day_pnl": round(day_pnl_total, 2),
        "day_pnl_pct": round(day_pnl_total / (market_value_total - day_pnl_total) * 100, 2)
        if market_value_total - day_pnl_total
        else 0,
    }

    holdings_alloc = [
        {"name": position["symbol"], "value": position["market_value"], "weight": position["weight"]}
        for position in positions
    ]
    sectors_alloc = [
        {"name": name, "value": round(value, 2), "weight": round(value / market_value_total * 100, 2)}
        for name, value in sorted(sector_values.items(), key=lambda item: item[1], reverse=True)
    ]

    frames = {}
    for symbol in active:
        bars = bars_map.get(symbol) or []
        series_data = {str(bar["t"]): float(bar["c"]) for bar in bars if bar.get("c") is not None}
        if len(series_data) >= 10:
            frames[symbol] = pd.Series(series_data)
    performance = {"dates": [], "portfolio": [], "benchmark": []}
    risk: dict[str, Any] = {}
    if frames:
        frame = pd.concat(frames, axis=1, join="inner").dropna().sort_index()
        weights = {}
        for position in positions:
            symbol = position["symbol"]
            if symbol in frame.columns:
                weights[symbol] = position["weight"] / 100
        weight_total = sum(weights.values())
        if weight_total > 0:
            weights = {symbol: value / weight_total for symbol, value in weights.items()}
        returns_frame = frame.pct_change().fillna(0)
        portfolio_returns = sum(returns_frame[symbol] * weight for symbol, weight in weights.items())
        cumulative = (1 + portfolio_returns).cumprod() * 100.0
        benchmark_series = None
        if benchmark_bars:
            bench = pd.Series(
                {str(bar["t"]): float(bar["c"]) for bar in benchmark_bars if bar.get("c") is not None}
            ).reindex(frame.index).ffill()
            if bench.notna().sum() >= 10:
                benchmark_series = bench
                bench_cumulative = bench / bench.dropna().iloc[0] * 100
        dates = [str(index) for index in cumulative.index]
        series_payload = {"portfolio": [round(float(value), 2) for value in cumulative.values]}
        if benchmark_series is not None:
            series_payload["benchmark"] = [
                None if pd.isna(value) else round(float(value), 2) for value in bench_cumulative.values
            ]
        sampled = _downsample_series(dates, series_payload)
        performance = {
            "dates": sampled["dates"],
            "portfolio": sampled["series"]["portfolio"],
            "benchmark": sampled["series"].get("benchmark", []),
        }
        risk = _series_metrics(
            portfolio_returns,
            benchmark_series.pct_change().reindex(portfolio_returns.index) if benchmark_series is not None else None,
        )

    return {
        "empty": False,
        "summary": summary,
        "positions": positions,
        "allocation": {"holdings": holdings_alloc, "sectors": sectors_alloc},
        "performance": performance,
        "risk": risk,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Portfolio backtest: target weights + buy & hold / periodic rebalancing
# ---------------------------------------------------------------------------

PORTFOLIO_REBALANCE_MODES = ("buy_hold", "monthly", "quarterly", "annual")

PORTFOLIO_METRIC_KEYS = (
    "total_return",
    "annual_return",
    "annualized_vol",
    "sharpe",
    "sortino",
    "max_drawdown",
    "calmar",
    "var_95_daily",
    "cvar_95_daily",
    "beta",
    "correlation",
    "tracking_error",
    "information_ratio",
    "upside_capture",
    "downside_capture",
)


def _portfolio_round(value: Any, digits: int = 2) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, digits)


def _portfolio_date_text(value: Any) -> str:
    text = str(value).strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return text


def _portfolio_json_safe(value: Any) -> Any:
    """Recursively replace NaN/Inf with None so FastAPI can emit strict JSON."""
    if isinstance(value, dict):
        return {str(key): _portfolio_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_portfolio_json_safe(item) for item in value]
    if isinstance(value, np.ndarray):
        return [_portfolio_json_safe(item) for item in value.tolist()]
    if isinstance(value, (float, np.floating)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if value is pd.NaT:
        return None
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    return value


def normalize_portfolio_weights(holdings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Clean symbols, keep request order, and normalize weights to 1.0."""
    if not isinstance(holdings, list) or not 1 <= len(holdings) <= 20:
        raise ValueError("组合需要 1 到 20 个持仓")
    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in holdings:
        if not isinstance(item, dict):
            raise ValueError("持仓格式无效")
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol:
            raise ValueError("持仓代码不能为空")
        if symbol in seen:
            raise ValueError(f"持仓代码重复：{symbol}")
        raw_weight = item.get("weight")
        if isinstance(raw_weight, bool) or not isinstance(raw_weight, (int, float)):
            raise ValueError(f"{symbol} 的目标权重必须是正数")
        try:
            weight = float(raw_weight)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{symbol} 的目标权重必须是正数") from exc
        if not math.isfinite(weight) or weight <= 0:
            raise ValueError(f"{symbol} 的目标权重必须是有限正数")
        seen.add(symbol)
        cleaned.append({"symbol": symbol, "weight": weight})
    total = math.fsum(item["weight"] for item in cleaned)
    if not math.isfinite(total) or total <= 0:
        raise ValueError("目标权重总和必须大于 0")
    for item in cleaned:
        item["normalized"] = item["weight"] / total
    return cleaned


def _portfolio_period_key(value: Any, rebalance: str) -> tuple[int, ...] | None:
    try:
        stamp = pd.Timestamp(_portfolio_date_text(value))
    except (TypeError, ValueError):
        return None
    if pd.isna(stamp):
        return None
    if rebalance == "monthly":
        return (int(stamp.year), int(stamp.month))
    if rebalance == "quarterly":
        return (int(stamp.year), (int(stamp.month) - 1) // 3 + 1)
    if rebalance == "annual":
        return (int(stamp.year),)
    return None


def portfolio_rebalance_dates(dates: list[Any], rebalance: str) -> list[str]:
    """First common trading day of each new month/quarter/year (excludes the start)."""
    if rebalance not in PORTFOLIO_REBALANCE_MODES:
        raise ValueError(f"不支持的再平衡频率：{rebalance}")
    if rebalance == "buy_hold":
        return []
    result: list[str] = []
    previous: tuple[int, ...] | None = None
    for value in dates:
        key = _portfolio_period_key(value, rebalance)
        if key is None:
            continue
        if previous is not None and key != previous:
            result.append(_portfolio_date_text(value))
        previous = key
    return result


def _portfolio_downsample(
    dates: list[str],
    series: dict[str, list[float]],
    max_points: int = 600,
) -> dict[str, Any]:
    length = len(dates)
    if length <= max_points:
        return {"dates": dates, "series": series}
    indices = np.unique(
        np.linspace(0, length - 1, max_points).round().astype(int)
    ).tolist()
    return {
        "dates": [dates[index] for index in indices],
        "series": {
            key: [values[index] for index in indices] for key, values in series.items()
        },
    }


def _portfolio_bars_series(bars: list[dict[str, Any]] | None) -> pd.Series:
    values: dict[str, float] = {}
    for bar in bars or []:
        if not isinstance(bar, dict):
            continue
        close = _as_float(bar.get("c"))
        stamp = bar.get("t") or bar.get("date")
        if stamp is None or close is None or not math.isfinite(close) or close <= 0:
            continue
        key = _portfolio_date_text(stamp)
        if not key:
            continue
        values[key] = close
    if not values:
        return pd.Series(dtype=float)
    series = pd.Series(values, dtype=float).sort_index()
    return series[~series.index.duplicated(keep="last")]


def simulate_portfolio(
    prices: pd.DataFrame,
    weights: dict[str, float],
    rebalance: str = "buy_hold",
) -> dict[str, Any]:
    """Simulate $100 across aligned closes; periodic rebalances use prior close values."""
    if rebalance not in PORTFOLIO_REBALANCE_MODES:
        raise ValueError(f"不支持的再平衡频率：{rebalance}")
    if not isinstance(prices, pd.DataFrame) or prices.empty:
        raise ValueError("价格序列为空")
    columns = [str(column) for column in prices.columns]
    raw_weights: list[float] = []
    for symbol in columns:
        raw = weights.get(symbol)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ValueError(f"{symbol} 缺少有效目标权重")
        value = float(raw)
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{symbol} 的目标权重必须是有限正数")
        raw_weights.append(value)
    total_weight = math.fsum(raw_weights)
    if total_weight <= 0:
        raise ValueError("目标权重总和必须大于 0")
    target = np.asarray([value / total_weight for value in raw_weights], dtype=float)

    frame = prices.copy().sort_index()
    values = frame.to_numpy(dtype=float)
    if len(frame) < 2:
        raise ValueError("至少需要 2 个共同交易日")
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("收盘价必须是有限正数")
    dates = [_portfolio_date_text(index) for index in frame.index]
    rebalance_set = set(portfolio_rebalance_dates(dates, rebalance))

    dollars = target * 100.0
    portfolio = [100.0]
    events: list[dict[str, Any]] = []
    cumulative_pnl = np.zeros(len(columns), dtype=float)
    weight_sum = target.astype(float).copy()
    for offset in range(1, len(frame)):
        if dates[offset] in rebalance_set:
            total_value = float(dollars.sum())
            target_dollars = target * total_value
            one_way = float(np.abs(target_dollars - dollars).sum() / (2.0 * total_value))
            events.append({"date": dates[offset], "turnover": one_way})
            dollars = target_dollars
        total_value = float(dollars.sum())
        weight_sum += dollars / total_value
        day_returns = values[offset] / values[offset - 1] - 1.0
        day_pnl = dollars * day_returns
        cumulative_pnl += day_pnl
        dollars = dollars + day_pnl
        portfolio.append(float(dollars.sum()))

    final_value = float(dollars.sum())
    end_weights = {
        symbol: float(amount / final_value) if final_value else None
        for symbol, amount in zip(columns, dollars)
    }
    return {
        "dates": dates,
        "portfolio": portfolio,
        "end_weights": end_weights,
        "target_weights": {symbol: float(weight) for symbol, weight in zip(columns, target)},
        "pnl": {symbol: float(value) for symbol, value in zip(columns, cumulative_pnl)},
        "average_weights": {
            symbol: float(value / len(frame))
            for symbol, value in zip(columns, weight_sum)
        },
        "turnover_events": events,
        "total_turnover": float(sum(event["turnover"] for event in events)),
    }


def _portfolio_empty_metrics() -> dict[str, Any]:
    return {key: None for key in PORTFOLIO_METRIC_KEYS}


def _portfolio_metrics(
    portfolio_values: pd.Series,
    benchmark_values: pd.Series | None = None,
) -> dict[str, Any]:
    metrics = _portfolio_empty_metrics()
    values = pd.Series(portfolio_values, dtype=float).dropna()
    if len(values) < 2:
        return metrics
    returns = values.pct_change(fill_method=None).dropna()
    count = len(returns)
    if count == 0:
        return metrics
    total_return = float(values.iloc[-1] / values.iloc[0] - 1.0)
    metrics["total_return"] = _portfolio_round(total_return * 100)
    annual_return: float | None = None
    if total_return > -1:
        annual_return = (1.0 + total_return) ** (252.0 / count) - 1.0
        metrics["annual_return"] = _portfolio_round(annual_return * 100)

    volatility: float | None = None
    if count >= 3:
        volatility = float(returns.std(ddof=1)) * math.sqrt(252)
        metrics["annualized_vol"] = _portfolio_round(volatility * 100)
        if annual_return is not None and volatility > 1e-12:
            metrics["sharpe"] = _portfolio_round((annual_return - RISK_FREE) / volatility)
        downside = returns[returns < 0]
        if len(downside) > 1:
            downside_volatility = float(downside.std(ddof=1)) * math.sqrt(252)
            if downside_volatility > 1e-12 and annual_return is not None:
                metrics["sortino"] = _portfolio_round(
                    (annual_return - RISK_FREE) / downside_volatility
                )

    drawdown = values / values.cummax() - 1.0
    max_drawdown = float(drawdown.min())
    metrics["max_drawdown"] = _portfolio_round(max_drawdown * 100)
    if annual_return is not None and max_drawdown < 0:
        metrics["calmar"] = _portfolio_round(annual_return / abs(max_drawdown))

    if count >= 20:
        threshold = float(np.percentile(returns.to_numpy(dtype=float), 5))
        metrics["var_95_daily"] = _portfolio_round(max(0.0, -threshold) * 100)
        tail = returns[returns <= threshold]
        if len(tail):
            metrics["cvar_95_daily"] = _portfolio_round(max(0.0, -float(tail.mean())) * 100)

    if benchmark_values is None:
        return metrics
    benchmark = pd.Series(benchmark_values, dtype=float).dropna()
    joined = pd.concat(
        [values.rename("portfolio"), benchmark.rename("benchmark")],
        axis=1,
        join="inner",
    ).dropna()
    if len(joined) < 3:
        return metrics
    bench_returns = joined["benchmark"].pct_change(fill_method=None).dropna()
    portfolio_returns = joined["portfolio"].pct_change(fill_method=None).dropna()
    if len(bench_returns) < 2 or len(portfolio_returns) < 2:
        return metrics
    bench_variance = float(bench_returns.var(ddof=1))
    if bench_variance > 1e-18:
        beta = float(portfolio_returns.cov(bench_returns, ddof=1)) / bench_variance
        metrics["beta"] = _portfolio_round(beta)
    portfolio_std = float(portfolio_returns.std(ddof=1))
    bench_std = float(bench_returns.std(ddof=1))
    if portfolio_std > 1e-12 and bench_std > 1e-12:
        metrics["correlation"] = _portfolio_round(portfolio_returns.corr(bench_returns))
    active = portfolio_returns - bench_returns
    active_std = float(active.std(ddof=1))
    tracking_error = active_std * math.sqrt(252)
    if tracking_error > 1e-12:
        metrics["tracking_error"] = _portfolio_round(tracking_error * 100)
        metrics["information_ratio"] = _portfolio_round(
            float(active.mean()) * 252.0 / tracking_error
        )
    up = bench_returns > 0
    if up.any():
        bench_up_mean = float(bench_returns[up].mean())
        if abs(bench_up_mean) > 1e-15:
            metrics["upside_capture"] = _portfolio_round(
                float(portfolio_returns[up].mean()) / bench_up_mean * 100
            )
    down = bench_returns < 0
    if down.any():
        bench_down_mean = float(bench_returns[down].mean())
        if abs(bench_down_mean) > 1e-15:
            metrics["downside_capture"] = _portfolio_round(
                float(portfolio_returns[down].mean()) / bench_down_mean * 100
            )
    return metrics


def _portfolio_asset_metrics(
    values: pd.Series,
    benchmark_returns: pd.Series | None = None,
) -> dict[str, Any]:
    result = {
        "annual_return": None,
        "volatility": None,
        "sharpe": None,
        "max_drawdown": None,
        "beta": None,
        "correlation": None,
    }
    series = pd.Series(values, dtype=float).dropna()
    if len(series) < 2:
        return result
    returns = series.pct_change(fill_method=None).dropna()
    count = len(returns)
    if count == 0:
        return result
    total_return = float(series.iloc[-1] / series.iloc[0] - 1.0)
    annual_return = None
    if total_return > -1:
        annual_return = (1.0 + total_return) ** (252.0 / count) - 1.0
        result["annual_return"] = _portfolio_round(annual_return * 100)
    if count >= 3:
        volatility = float(returns.std(ddof=1)) * math.sqrt(252)
        result["volatility"] = _portfolio_round(volatility * 100)
        if annual_return is not None and volatility > 1e-12:
            result["sharpe"] = _portfolio_round((annual_return - RISK_FREE) / volatility)
    drawdown = series / series.cummax() - 1.0
    result["max_drawdown"] = _portfolio_round(float(drawdown.min()) * 100)
    if benchmark_returns is not None:
        joined = pd.concat(
            [returns.rename("asset"), benchmark_returns.rename("benchmark")],
            axis=1,
            join="inner",
        ).dropna()
        if len(joined) >= 3:
            bench_var = float(joined["benchmark"].var(ddof=1))
            if bench_var > 1e-18:
                result["beta"] = _portfolio_round(
                    float(joined["asset"].cov(joined["benchmark"], ddof=1)) / bench_var
                )
            asset_std = float(joined["asset"].std(ddof=1))
            bench_std = float(joined["benchmark"].std(ddof=1))
            if asset_std > 1e-12 and bench_std > 1e-12:
                result["correlation"] = _portfolio_round(
                    joined["asset"].corr(joined["benchmark"])
                )
    return result


def _portfolio_annual_returns(
    dates: list[str],
    portfolio_values: list[float],
    benchmark_values: list[float] | None = None,
) -> list[dict[str, Any]]:
    if not dates:
        return []
    index = pd.to_datetime(pd.Index(dates), errors="coerce")
    frame = pd.DataFrame({"portfolio": np.asarray(portfolio_values, dtype=float)}, index=index)
    if benchmark_values is not None and len(benchmark_values) == len(portfolio_values):
        frame["benchmark"] = np.asarray(benchmark_values, dtype=float)
    frame = frame[~frame.index.isna()]
    if frame.empty:
        return []
    rows: list[dict[str, Any]] = []
    previous_portfolio = 100.0
    previous_benchmark = 100.0 if "benchmark" in frame else None
    for year in sorted({int(value) for value in frame.index.year}):
        group = frame[frame.index.year == year]
        if group.empty:
            continue
        last = group.iloc[-1]
        row: dict[str, Any] = {
            "year": year,
            "portfolio": _portfolio_round(
                (float(last["portfolio"]) / previous_portfolio - 1.0) * 100
                if previous_portfolio
                else None
            ),
            "benchmark": None,
        }
        if previous_benchmark and "benchmark" in group:
            row["benchmark"] = _portfolio_round(
                (float(last["benchmark"]) / previous_benchmark - 1.0) * 100
            )
        rows.append(row)
        previous_portfolio = float(last["portfolio"])
        if "benchmark" in group:
            previous_benchmark = float(last["benchmark"])
    return rows


def _portfolio_monthly_returns(
    dates: list[str],
    portfolio_values: list[float],
    benchmark_values: list[float] | None = None,
    limit: int = 60,
) -> list[dict[str, Any]]:
    if not dates:
        return []
    index = pd.to_datetime(pd.Index(dates), errors="coerce")
    frame = pd.DataFrame({"portfolio": np.asarray(portfolio_values, dtype=float)}, index=index)
    if benchmark_values is not None and len(benchmark_values) == len(portfolio_values):
        frame["benchmark"] = np.asarray(benchmark_values, dtype=float)
    frame = frame[~frame.index.isna()]
    if frame.empty:
        return []
    grouped = frame.groupby(frame.index.to_period("M")).last()
    rows: list[dict[str, Any]] = []
    previous_portfolio = 100.0
    previous_benchmark = 100.0 if "benchmark" in frame else None
    for period, row in grouped.iterrows():
        item: dict[str, Any] = {
            "month": str(period),
            "portfolio": _portfolio_round(
                (float(row["portfolio"]) / previous_portfolio - 1.0) * 100
                if previous_portfolio
                else None
            ),
            "benchmark": None,
        }
        if previous_benchmark and "benchmark" in row:
            item["benchmark"] = _portfolio_round(
                (float(row["benchmark"]) / previous_benchmark - 1.0) * 100
            )
        rows.append(item)
        previous_portfolio = float(row["portfolio"])
        if "benchmark" in row:
            previous_benchmark = float(row["benchmark"])
    return rows[-limit:]


def _portfolio_risk_decomposition(
    normalized: list[dict[str, Any]],
    prices: pd.DataFrame,
) -> dict[str, Any]:
    symbols = [item["symbol"] for item in normalized]
    weights = np.asarray([float(item["normalized"]) for item in normalized], dtype=float)
    empty = {
        "concentration": {
            "hhi": None,
            "effective_holdings": None,
            "top1_weight": None,
            "top3_weight": None,
            "top5_weight": None,
            "max_weight": None,
        },
        "diversification": {
            "weighted_volatility": None,
            "portfolio_volatility": None,
            "ratio": None,
            "benefit_pct": None,
            "risk_hhi": None,
            "effective_risk_bets": None,
        },
        "risk_by_symbol": {},
        "correlation": {"symbols": symbols, "matrix": []},
    }
    if len(symbols) == 0 or len(prices) < 3:
        return empty

    weights_pct = weights * 100.0
    sorted_weights = np.sort(weights_pct)[::-1]
    hhi = float(np.sum(weights**2))
    concentration = {
        "hhi": _portfolio_round(hhi, 4),
        "effective_holdings": _portfolio_round(1.0 / hhi, 2) if hhi > 0 else None,
        "top1_weight": _portfolio_round(sorted_weights[0]) if len(sorted_weights) else None,
        "top3_weight": _portfolio_round(float(sorted_weights[:3].sum())),
        "top5_weight": _portfolio_round(float(sorted_weights[:5].sum())),
        "max_weight": _portfolio_round(sorted_weights[0]) if len(sorted_weights) else None,
    }

    aligned = prices[symbols].astype(float)
    returns = aligned.pct_change(fill_method=None).dropna(how="any")
    if len(returns) < 3:
        return {**empty, "concentration": concentration}

    covariance = returns.cov().reindex(index=symbols, columns=symbols).to_numpy(dtype=float)
    if not np.isfinite(covariance).all():
        return {**empty, "concentration": concentration}
    variance = float(weights @ covariance @ weights)
    if not math.isfinite(variance) or variance <= 1e-18:
        return {**empty, "concentration": concentration}
    daily_vol = math.sqrt(variance)
    annual_vol = daily_vol * math.sqrt(252.0)
    covariance_times_weights = covariance @ weights
    risk_dollars = weights * covariance_times_weights
    risk_share = risk_dollars / variance * 100.0
    asset_volatility = returns.std(ddof=1).reindex(symbols).to_numpy(dtype=float) * math.sqrt(252.0)
    weighted_vol = float(np.sum(weights * asset_volatility))
    positive_share = np.clip(risk_share, 0.0, None)
    positive_total = float(positive_share.sum())
    risk_hhi = None
    effective_risk_bets = None
    if positive_total > 1e-12:
        normalized_share = positive_share / positive_total
        risk_hhi = float(np.sum(normalized_share**2))
        if risk_hhi > 0:
            effective_risk_bets = 1.0 / risk_hhi

    correlation = returns.corr().reindex(index=symbols, columns=symbols)
    matrix = [
        [_portfolio_round(value, 4) for value in row]
        for row in correlation.to_numpy(dtype=float).tolist()
    ]
    return {
        "concentration": concentration,
        "diversification": {
            "weighted_volatility": _portfolio_round(weighted_vol * 100),
            "portfolio_volatility": _portfolio_round(annual_vol * 100),
            "ratio": _portfolio_round(weighted_vol / annual_vol, 3) if annual_vol > 1e-12 else None,
            "benefit_pct": _portfolio_round((1.0 - annual_vol / weighted_vol) * 100.0) if weighted_vol > 1e-12 else None,
            "risk_hhi": _portfolio_round(risk_hhi, 4),
            "effective_risk_bets": _portfolio_round(effective_risk_bets, 2),
        },
        "risk_by_symbol": {
            symbol: _portfolio_round(value)
            for symbol, value in zip(symbols, risk_share)
        },
        "correlation": {"symbols": symbols, "matrix": matrix},
    }


def _portfolio_rolling_risk(
    dates: list[str],
    portfolio_values: list[float],
    benchmark_values: list[float] | None = None,
    window: int = 60,
    max_points: int = 320,
) -> dict[str, Any]:
    result = {
        "window": window,
        "dates": [],
        "portfolio_vol": [],
        "benchmark_vol": [],
        "beta": [],
    }
    if len(dates) < window + 10 or len(portfolio_values) != len(dates):
        return result
    values = pd.Series(portfolio_values, dtype=float)
    returns = values.pct_change(fill_method=None)
    portfolio_vol = returns.rolling(window, min_periods=window).std(ddof=1) * math.sqrt(252.0) * 100.0
    benchmark_vol = pd.Series(dtype=float)
    beta = pd.Series(dtype=float)
    if benchmark_values is not None and len(benchmark_values) == len(portfolio_values):
        bench = pd.Series(benchmark_values, dtype=float)
        bench_returns = bench.pct_change(fill_method=None)
        benchmark_vol = bench_returns.rolling(window, min_periods=window).std(ddof=1) * math.sqrt(252.0) * 100.0
        bench_var = bench_returns.rolling(window, min_periods=window).var(ddof=1)
        beta = returns.rolling(window, min_periods=window).cov(bench_returns, ddof=1) / bench_var
    valid = portfolio_vol.notna()
    if not valid.any():
        return result
    positions = np.flatnonzero(valid.to_numpy())
    if len(positions) > max_points:
        sample = np.unique(np.linspace(0, len(positions) - 1, max_points).round().astype(int))
        positions = positions[sample]
    result["dates"] = [dates[int(index)] for index in positions]
    result["portfolio_vol"] = [
        _portfolio_round(portfolio_vol.iloc[int(index)], 2) for index in positions
    ]
    if not benchmark_vol.empty:
        result["benchmark_vol"] = [
            _portfolio_round(benchmark_vol.iloc[int(index)], 2) for index in positions
        ]
        result["beta"] = [_portfolio_round(beta.iloc[int(index)], 3) for index in positions]
    return result


def _portfolio_drawdown_episodes(
    dates: list[str],
    values: list[float],
    limit: int = 3,
) -> list[dict[str, Any]]:
    if len(dates) < 2 or len(values) != len(dates):
        return []
    episodes: list[dict[str, Any]] = []
    peak_index = 0
    trough_index = 0
    in_drawdown = False
    depth = 0.0

    def close_episode(recovery_index: int | None) -> None:
        nonlocal in_drawdown, depth
        if not in_drawdown:
            return
        episodes.append(
            {
                "peak_date": dates[peak_index],
                "trough_date": dates[trough_index],
                "recovery_date": dates[recovery_index] if recovery_index is not None else None,
                "depth_pct": _portfolio_round(depth * 100),
                "decline_sessions": trough_index - peak_index,
                "recovery_sessions": recovery_index - trough_index if recovery_index is not None else None,
                "recovered": recovery_index is not None,
            }
        )
        in_drawdown = False
        depth = 0.0

    for index in range(1, len(values)):
        if values[index] >= values[peak_index]:
            close_episode(index)
            peak_index = index
            trough_index = index
            continue
        drawdown_value = values[index] / values[peak_index] - 1.0
        in_drawdown = True
        if drawdown_value < depth:
            depth = drawdown_value
            trough_index = index
    close_episode(None)
    episodes.sort(key=lambda item: item["depth_pct"] if item["depth_pct"] is not None else 0.0)
    return episodes[:limit]


def _portfolio_stress_windows(
    dates: list[str],
    values: list[float],
    benchmark_values: list[float] | None = None,
) -> list[dict[str, Any]]:
    if len(dates) < 25 or len(values) != len(dates):
        return []
    prices = np.asarray(values, dtype=float)
    benchmark = (
        np.asarray(benchmark_values, dtype=float)
        if benchmark_values is not None and len(benchmark_values) == len(values)
        else None
    )
    rows: list[dict[str, Any]] = []
    for window in (20, 60):
        if len(prices) <= window:
            continue
        window_returns = prices[window:] / prices[:-window] - 1.0
        index = int(np.argmin(window_returns))
        benchmark_return = None
        if benchmark is not None:
            benchmark_return = _portfolio_round((benchmark[index + window] / benchmark[index] - 1.0) * 100)
        rows.append(
            {
                "window": window,
                "label": f"最差 {window} 个交易日",
                "portfolio_return": _portfolio_round(float(window_returns[index]) * 100),
                "benchmark_return": benchmark_return,
                "start": dates[index],
                "end": dates[index + window],
            }
        )
    return rows


def _portfolio_holding_rows(
    normalized: list[dict[str, Any]],
    prices: pd.DataFrame,
    benchmark_returns: pd.Series | None,
    bars_map: dict[str, Any],
    names: dict[str, str],
    sector_map: dict[str, str],
    *,
    risk_by_symbol: dict[str, Any] | None = None,
    pnl: dict[str, float] | None = None,
    average_weights: dict[str, float] | None = None,
    initial_value: float = 100.0,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    risk_map = risk_by_symbol or {}
    pnl_map = pnl or {}
    average_map = average_weights or {}
    for item in normalized:
        symbol = item["symbol"]
        entry = bars_map.get(symbol)
        if isinstance(entry, dict):
            source = entry.get("source")
            price_basis = entry.get("price_basis")
        else:
            source = None
            price_basis = None
        stats = _portfolio_asset_metrics(prices[symbol], benchmark_returns)
        effective_weight = _portfolio_round(item["normalized"] * 100)
        contribution = None
        if symbol in pnl_map and initial_value > 0:
            contribution = _portfolio_round(pnl_map[symbol] / initial_value * 100.0)
        rows.append(
            {
                "symbol": symbol,
                "name": names.get(symbol) or symbol,
                "weight": effective_weight,
                "target_weight": effective_weight,
                "average_weight": _portfolio_round((average_map.get(symbol) or 0.0) * 100.0),
                "sector": sector_map.get(symbol) or "其他",
                "annual_return": stats["annual_return"],
                "volatility": stats["volatility"],
                "sharpe": stats["sharpe"],
                "max_drawdown": stats["max_drawdown"],
                "beta": stats["beta"],
                "correlation": stats["correlation"],
                "return_contribution": contribution,
                "risk_contribution": risk_map.get(symbol),
                "source": source,
                "price_basis": price_basis,
            }
        )
    return rows


def _portfolio_allocation(
    normalized: list[dict[str, Any]],
    names: dict[str, str],
    sector_map: dict[str, str],
) -> dict[str, list[dict[str, Any]]]:
    holdings_alloc: list[dict[str, Any]] = []
    sector_values: dict[str, float] = {}
    for item in normalized:
        symbol = item["symbol"]
        weight = float(item["normalized"]) * 100.0
        holdings_alloc.append(
            {
                "symbol": symbol,
                "name": names.get(symbol) or symbol,
                "value": _portfolio_round(weight),
                "weight": _portfolio_round(weight),
            }
        )
        sector = sector_map.get(symbol) or "其他"
        sector_values[sector] = sector_values.get(sector, 0.0) + weight
    sectors = [
        {
            "name": name,
            "value": _portfolio_round(weight),
            "weight": _portfolio_round(weight),
        }
        for name, weight in sorted(sector_values.items(), key=lambda pair: pair[1], reverse=True)
    ]
    return {"holdings": holdings_alloc, "sectors": sectors}


def _portfolio_source_summary(
    normalized: list[dict[str, Any]],
    bars_map: dict[str, Any],
) -> tuple[str | None, str | None]:
    sources: set[str] = set()
    bases: set[str] = set()
    for item in normalized:
        entry = bars_map.get(item["symbol"])
        if not isinstance(entry, dict) or not entry.get("bars"):
            continue
        source = str(entry.get("source") or "").strip()
        basis = str(entry.get("price_basis") or "").strip()
        if source:
            sources.add(source)
        if basis:
            bases.add(basis)

    def pick(values: set[str]) -> str | None:
        if not values:
            return None
        if len(values) == 1:
            return next(iter(values))
        return "mixed"

    return pick(sources), pick(bases)


def _portfolio_empty_result(
    message: str,
    normalized: list[dict[str, Any]],
    range_name: str,
    benchmark: str,
    rebalance: str,
    *,
    common_days: int = 0,
    start: str | None = None,
    end: str | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    summary = {
        "holdings": len(normalized),
        "holdings_count": len(normalized),
        "range": range_name,
        "rebalance": rebalance,
        "benchmark": benchmark,
        "common_days": common_days,
        "start": start,
        "end": end,
        "turnover_count": 0,
        "annual_turnover_est": None,
        "total_turnover": 0.0,
        "ex_fees": True,
    }
    return _portfolio_json_safe(
        {
            "empty": True,
            "error": message,
            "source": None,
            "price_basis": None,
            "ex_fees": True,
            "summary": summary,
            "performance": {"dates": [], "portfolio": [], "benchmark": []},
            "drawdown": {
                "dates": [],
                "portfolio": [],
                "benchmark": [],
                "series": {"portfolio": [], "benchmark": []},
            },
            "metrics": _portfolio_empty_metrics(),
            "annual_returns": [],
            "monthly_returns": [],
            "turnover_events": [],
            "holdings": [],
            "allocation": {"holdings": [], "sectors": []},
            "risk": {
                "concentration": {
                    "hhi": None,
                    "effective_holdings": None,
                    "top1_weight": None,
                    "top3_weight": None,
                    "top5_weight": None,
                    "max_weight": None,
                },
                "diversification": {
                    "weighted_volatility": None,
                    "portfolio_volatility": None,
                    "ratio": None,
                    "benefit_pct": None,
                    "risk_hhi": None,
                    "effective_risk_bets": None,
                },
                "correlation": {"symbols": [], "matrix": []},
                "rolling": {
                    "window": 60,
                    "dates": [],
                    "portfolio_vol": [],
                    "benchmark_vol": [],
                    "beta": [],
                },
                "drawdown_episodes": [],
                "stress_windows": [],
            },
            "warnings": list(dict.fromkeys(warnings or [])),
        }
    )


def backtest_portfolio(
    holdings: list[dict[str, Any]],
    bars_map: dict[str, Any],
    benchmark_bars: list[dict[str, Any]] | None = None,
    benchmark: str = "SPY",
    rebalance: str = "buy_hold",
    range_name: str = "1Y",
    names: dict[str, str] | None = None,
    sector_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Backtest target-weight holdings on the strict inner common trading calendar."""
    names = names or {}
    sector_map = sector_map or {}
    warnings: list[str] = []
    try:
        normalized = normalize_portfolio_weights(holdings)
    except ValueError as exc:
        return _portfolio_empty_result(
            str(exc), [], range_name, benchmark, rebalance, warnings=warnings
        )
    if rebalance not in PORTFOLIO_REBALANCE_MODES:
        return _portfolio_empty_result(
            f"不支持的再平衡频率：{rebalance}",
            normalized,
            range_name,
            benchmark,
            rebalance,
            warnings=warnings,
        )

    series_map: dict[str, pd.Series] = {}
    missing: list[str] = []
    for item in normalized:
        symbol = item["symbol"]
        entry = bars_map.get(symbol)
        bars = entry.get("bars") if isinstance(entry, dict) else entry
        series = _portfolio_bars_series(bars)
        if series.empty:
            missing.append(symbol)
            continue
        series_map[symbol] = series
    if missing:
        message = "以下标的缺少历史行情：" + "、".join(missing)
        warnings.append(message)
        return _portfolio_empty_result(
            message,
            normalized,
            range_name,
            benchmark,
            rebalance,
            warnings=warnings,
        )

    benchmark_series = _portfolio_bars_series(benchmark_bars)
    if benchmark_bars and benchmark_series.empty:
        warnings.append(f"基准 {benchmark} 没有有效收盘价，已跳过基准对比。")

    frame = pd.concat(series_map, axis=1, join="inner").dropna().sort_index()
    benchmark_usable = not benchmark_series.empty
    if benchmark_usable:
        frame = pd.concat(
            [frame, benchmark_series.rename("__benchmark__")],
            axis=1,
            join="inner",
        ).dropna().sort_index()
    common_days = len(frame)
    dates = [_portfolio_date_text(index) for index in frame.index]
    start = dates[0] if dates else None
    end = dates[-1] if dates else None
    if common_days < 60:
        message = f"共同交易日仅 {common_days} 天，少于 60 天，无法回测。"
        warnings.append(message)
        return _portfolio_empty_result(
            message,
            normalized,
            range_name,
            benchmark,
            rebalance,
            common_days=common_days,
            start=start,
            end=end,
            warnings=warnings,
        )

    symbols = [item["symbol"] for item in normalized]
    prices = frame[symbols].copy()
    target_weights = {item["symbol"]: item["normalized"] for item in normalized}
    simulation = simulate_portfolio(prices, target_weights, rebalance)
    portfolio_values = pd.Series(simulation["portfolio"], index=simulation["dates"], dtype=float)
    if benchmark_usable:
        benchmark_raw = frame["__benchmark__"].astype(float)
        benchmark_normalized = benchmark_raw / float(benchmark_raw.iloc[0]) * 100.0
        benchmark_returns = benchmark_raw.pct_change(fill_method=None).dropna()
        benchmark_series_for_metrics: pd.Series | None = benchmark_raw
        benchmark_values_for_annual = benchmark_normalized.tolist()
    else:
        benchmark_returns = None
        benchmark_series_for_metrics = None
        benchmark_values_for_annual = None

    metrics = _portfolio_metrics(portfolio_values, benchmark_series_for_metrics)
    annual_returns = _portfolio_annual_returns(
        simulation["dates"],
        simulation["portfolio"],
        benchmark_values_for_annual,
    )
    monthly_returns = _portfolio_monthly_returns(
        simulation["dates"],
        simulation["portfolio"],
        benchmark_values_for_annual,
    )
    risk_decomposition = _portfolio_risk_decomposition(normalized, prices)
    rolling_risk = _portfolio_rolling_risk(
        simulation["dates"],
        simulation["portfolio"],
        benchmark_values_for_annual,
    )
    drawdown_episodes = _portfolio_drawdown_episodes(
        simulation["dates"], simulation["portfolio"]
    )
    stress_windows = _portfolio_stress_windows(
        simulation["dates"],
        simulation["portfolio"],
        benchmark_values_for_annual,
    )
    holding_rows = _portfolio_holding_rows(
        normalized,
        prices,
        benchmark_returns,
        bars_map,
        names,
        sector_map,
        risk_by_symbol=risk_decomposition["risk_by_symbol"],
        pnl=simulation["pnl"],
        average_weights=simulation["average_weights"],
    )
    allocation = _portfolio_allocation(normalized, names, sector_map)
    source, price_basis = _portfolio_source_summary(normalized, bars_map)

    series_payload: dict[str, list[float]] = {
        "portfolio": [float(value) for value in simulation["portfolio"]]
    }
    drawdown_payload: dict[str, list[float]] = {}
    portfolio_drawdown = (
        np.asarray(simulation["portfolio"], dtype=float)
        / np.maximum.accumulate(np.asarray(simulation["portfolio"], dtype=float))
        - 1.0
    )
    drawdown_payload["portfolio"] = [
        float(value) * 100.0 for value in portfolio_drawdown
    ]
    if benchmark_usable:
        series_payload["benchmark"] = [float(value) for value in benchmark_normalized]
        benchmark_drawdown = (
            benchmark_normalized.to_numpy(dtype=float)
            / np.maximum.accumulate(benchmark_normalized.to_numpy(dtype=float))
            - 1.0
        )
        drawdown_payload["benchmark"] = [
            float(value) * 100.0 for value in benchmark_drawdown
        ]

    sampled_performance = _portfolio_downsample(
        simulation["dates"], series_payload, max_points=600
    )
    sampled_drawdown = _portfolio_downsample(
        simulation["dates"], drawdown_payload, max_points=600
    )
    performance = {
        "dates": sampled_performance["dates"],
        "portfolio": [round(value, 2) for value in sampled_performance["series"]["portfolio"]],
        "benchmark": [
            round(value, 2)
            for value in sampled_performance["series"].get("benchmark", [])
        ],
    }
    drawdown = {
        "dates": sampled_drawdown["dates"],
        "portfolio": [round(value, 2) for value in sampled_drawdown["series"]["portfolio"]],
        "benchmark": [
            round(value, 2)
            for value in sampled_drawdown["series"].get("benchmark", [])
        ],
    }
    drawdown["series"] = {
        "portfolio": list(drawdown["portfolio"]),
        "benchmark": list(drawdown["benchmark"]),
    }

    turnover_events = [
        {
            "date": event["date"],
            "turnover": _portfolio_round(event["turnover"] * 100),
        }
        for event in simulation["turnover_events"]
    ]
    total_turnover = simulation["total_turnover"] * 100.0
    years = 0.0
    if start and end:
        years = (pd.Timestamp(end) - pd.Timestamp(start)).days / 365.25
    annual_turnover: float | None
    if rebalance == "buy_hold":
        annual_turnover = 0.0
    elif years > 0:
        annual_turnover = total_turnover / years
    else:
        annual_turnover = None

    summary = {
        "holdings": len(normalized),
        "holdings_count": len(normalized),
        "range": range_name,
        "rebalance": rebalance,
        "benchmark": benchmark,
        "common_days": common_days,
        "start": start,
        "end": end,
        "turnover_count": len(turnover_events),
        "annual_turnover_est": _portfolio_round(annual_turnover),
        "total_turnover": _portfolio_round(total_turnover),
        "ex_fees": True,
    }
    return _portfolio_json_safe(
        {
            "empty": False,
            "error": None,
            "source": source,
            "price_basis": price_basis,
            "ex_fees": True,
            "summary": summary,
            "performance": performance,
            "drawdown": drawdown,
            "metrics": metrics,
            "annual_returns": annual_returns,
            "monthly_returns": monthly_returns,
            "turnover_events": turnover_events,
            "holdings": holding_rows,
            "allocation": allocation,
            "risk": {
                "concentration": risk_decomposition["concentration"],
                "diversification": risk_decomposition["diversification"],
                "correlation": risk_decomposition["correlation"],
                "rolling": rolling_risk,
                "drawdown_episodes": drawdown_episodes,
                "stress_windows": stress_windows,
            },
            "warnings": list(dict.fromkeys(warnings)),
        }
    )
