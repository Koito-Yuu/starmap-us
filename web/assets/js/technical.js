export const DEFAULT_INDICATOR_PARAMS = Object.freeze({
  ma_periods: [5, 20, 50, 200],
  macd_fast: 12,
  macd_slow: 26,
  macd_signal: 9,
  rsi_period: 14,
  bb_period: 20,
  bb_mult: 2,
  kc_period: 20,
  kc_atr_period: 20,
  kc_mult: 2,
  donchian_period: 20,
  regression_period: 60,
  regression_mult: 2,
  vwap_period: 20,
  vwap_mult: 2,
  adaptive_period: 10,
  adaptive_fast: 2,
  adaptive_slow: 30,
  adaptive_atr_period: 14,
  adaptive_mult: 1.5,
  supertrend_period: 10,
  supertrend_mult: 3,
  kama_period: 10,
  kama_fast: 2,
  kama_slow: 30,
  adx_period: 14,
  stoch_period: 14,
  stoch_k: 3,
  stoch_d: 3,
  cmf_period: 20,
  atr_period: 14,
  squeeze_bb_period: 20,
  squeeze_bb_mult: 2,
  squeeze_kc_period: 20,
  squeeze_kc_mult: 1.5,
  squeeze_momentum_period: 20,
});

export const PARAM_RANGES = {
  macd_fast: { min: 2, max: 100 },
  macd_slow: { min: 3, max: 200 },
  macd_signal: { min: 2, max: 100 },
  rsi_period: { min: 2, max: 200 },
  bb_period: { min: 5, max: 200 },
  bb_mult: { min: 0.5, max: 5, step: 0.1 },
  kc_period: { min: 5, max: 200 },
  kc_atr_period: { min: 2, max: 200 },
  kc_mult: { min: 0.5, max: 5, step: 0.1 },
  donchian_period: { min: 2, max: 200 },
  regression_period: { min: 10, max: 200 },
  regression_mult: { min: 0.5, max: 5, step: 0.1 },
  vwap_period: { min: 2, max: 200 },
  vwap_mult: { min: 0.5, max: 5, step: 0.1 },
  adaptive_period: { min: 2, max: 100 },
  adaptive_fast: { min: 2, max: 50 },
  adaptive_slow: { min: 5, max: 200 },
  adaptive_atr_period: { min: 2, max: 100 },
  adaptive_mult: { min: 0.5, max: 5, step: 0.1 },
  supertrend_period: { min: 2, max: 100 },
  supertrend_mult: { min: 0.5, max: 10, step: 0.1 },
  kama_period: { min: 2, max: 100 },
  kama_fast: { min: 2, max: 50 },
  kama_slow: { min: 5, max: 200 },
  adx_period: { min: 2, max: 100 },
  stoch_period: { min: 2, max: 100 },
  stoch_k: { min: 1, max: 20 },
  stoch_d: { min: 1, max: 20 },
  cmf_period: { min: 2, max: 100 },
  atr_period: { min: 2, max: 100 },
  squeeze_bb_period: { min: 5, max: 100 },
  squeeze_bb_mult: { min: 0.5, max: 5, step: 0.1 },
  squeeze_kc_period: { min: 5, max: 100 },
  squeeze_kc_mult: { min: 0.5, max: 5, step: 0.1 },
  squeeze_momentum_period: { min: 5, max: 100 },
};

export const CHANNEL_PARAMS = {
  none: [],
  bb: [
    { key: 'bb_period', label: '均线周期' },
    { key: 'bb_mult', label: '标准差倍数' },
  ],
  kc: [
    { key: 'kc_period', label: '中心周期' },
    { key: 'kc_atr_period', label: 'ATR 周期' },
    { key: 'kc_mult', label: 'ATR 倍数' },
  ],
  donchian: [{ key: 'donchian_period', label: '回看周期' }],
  regression: [
    { key: 'regression_period', label: '回归周期' },
    { key: 'regression_mult', label: '残差倍数' },
  ],
  vwap: [
    { key: 'vwap_period', label: '成交量窗口' },
    { key: 'vwap_mult', label: '偏离倍数' },
  ],
  adaptive: [
    { key: 'adaptive_period', label: 'KAMA 周期' },
    { key: 'adaptive_fast', label: '快线' },
    { key: 'adaptive_slow', label: '慢线' },
    { key: 'adaptive_atr_period', label: 'ATR 周期' },
    { key: 'adaptive_mult', label: '带宽倍数' },
  ],
};

export const TREND_PARAMS = {
  none: [],
  supertrend: [
    { key: 'supertrend_period', label: 'ATR 周期' },
    { key: 'supertrend_mult', label: 'ATR 倍数' },
  ],
  kama: [
    { key: 'kama_period', label: '效率周期' },
    { key: 'kama_fast', label: '快线' },
    { key: 'kama_slow', label: '慢线' },
  ],
};

export const STUDY_PARAMS = {
  none: [],
  adx: [{ key: 'adx_period', label: '平滑周期' }],
  stochastic: [
    { key: 'stoch_period', label: '回看周期' },
    { key: 'stoch_k', label: '%K 平滑' },
    { key: 'stoch_d', label: '%D 平滑' },
  ],
  cmf: [{ key: 'cmf_period', label: '累计周期' }],
  obv: [],
  atr: [{ key: 'atr_period', label: 'ATR 周期' }],
  squeeze: [
    { key: 'squeeze_bb_period', label: 'BB 周期' },
    { key: 'squeeze_bb_mult', label: 'BB 倍数' },
    { key: 'squeeze_momentum_period', label: '动量周期' },
    { key: 'squeeze_kc_period', label: 'KC 周期' },
    { key: 'squeeze_kc_mult', label: 'KC 倍数' },
  ],
};

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function readNumber(raw, fallback, { min, max, step = 1 }) {
  const number = Number(raw);
  if (!Number.isFinite(number)) return fallback;
  const clamped = clamp(number, min, max);
  return step >= 1 ? Math.round(clamped) : Number(clamped.toFixed(step < 0.1 ? 2 : 1));
}

export function sanitizeIndicatorParams(raw) {
  const source = raw && typeof raw === 'object' ? raw : {};
  const next = { ...DEFAULT_INDICATOR_PARAMS };
  for (const [key, range] of Object.entries(PARAM_RANGES)) {
    next[key] = readNumber(source[key], DEFAULT_INDICATOR_PARAMS[key], range);
  }
  const periods = Array.isArray(source.ma_periods)
    ? source.ma_periods.map((value) => Number(value))
    : [];
  if (
    periods.length === 4
    && periods.every((value) => Number.isInteger(value) && value >= 2 && value <= 300)
    && new Set(periods).size === 4
  ) {
    next.ma_periods = [...periods].sort((a, b) => a - b);
  }
  if (next.macd_fast >= next.macd_slow) {
    next.macd_fast = DEFAULT_INDICATOR_PARAMS.macd_fast;
    next.macd_slow = DEFAULT_INDICATOR_PARAMS.macd_slow;
  }
  if (next.kama_fast >= next.kama_slow) {
    next.kama_fast = DEFAULT_INDICATOR_PARAMS.kama_fast;
    next.kama_slow = DEFAULT_INDICATOR_PARAMS.kama_slow;
  }
  if (next.adaptive_fast >= next.adaptive_slow) {
    next.adaptive_fast = DEFAULT_INDICATOR_PARAMS.adaptive_fast;
    next.adaptive_slow = DEFAULT_INDICATOR_PARAMS.adaptive_slow;
  }
  return next;
}

export function formatParam(value) {
  return Number.isInteger(value) ? String(value) : Number(value).toFixed(1).replace(/\.0$/, '');
}

export function channelSummary(key, params) {
  if (key === 'bb') return `SMA${params.bb_period} · ±${formatParam(params.bb_mult)}σ`;
  if (key === 'kc') return `EMA${params.kc_period} · ${formatParam(params.kc_mult)}×ATR${params.kc_atr_period}`;
  if (key === 'donchian') return `前 ${params.donchian_period} 根`;
  if (key === 'regression') return `${params.regression_period} 根 · ±${formatParam(params.regression_mult)}σ`;
  if (key === 'vwap') return `${params.vwap_period} 根 · ±${formatParam(params.vwap_mult)}σ`;
  if (key === 'adaptive') return `KAMA${params.adaptive_period} · ±ATR${params.adaptive_atr_period}`;
  return '';
}

export function trendSummary(key, params) {
  if (key === 'supertrend') return `ATR${params.supertrend_period} · ${formatParam(params.supertrend_mult)}×`;
  if (key === 'kama') return `${params.kama_period} / ${params.kama_fast} / ${params.kama_slow}`;
  return '';
}

export function studySummary(key, params) {
  if (key === 'adx') return `Wilder ${params.adx_period}`;
  if (key === 'stochastic') return `${params.stoch_period} / ${params.stoch_k} / ${params.stoch_d}`;
  if (key === 'cmf') return `${params.cmf_period} 根`;
  if (key === 'obv') return '累计成交量';
  if (key === 'atr') return `${params.atr_period} 根 · %`;
  if (key === 'squeeze') return `BB${params.squeeze_bb_period} · KC${params.squeeze_kc_period}`;
  return '';
}
