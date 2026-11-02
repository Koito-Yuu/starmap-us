import {
  cssVar,
  hexToRgba,
  fmtCompact,
  fmtNum,
  fmtPct,
  fmtPrice,
  isNum,
  num,
} from './utils.js';

const registry = new Map();
const live = new Set();

const FONT = "Inter, 'Noto Sans SC', 'Segoe UI', system-ui, sans-serif";

const C = {
  get text() { return color('--chart-text', '#e9eefb'); },
  get dim() { return color('--chart-dim', '#9aa9c1'); },
  get mute() { return color('--chart-mute', '#61718c'); },
  get border() { return color('--chart-border', 'rgba(126, 160, 214, 0.14)'); },
  get grid() { return color('--chart-grid', 'rgba(126, 160, 214, 0.075)'); },
};

const resizeObserver = new ResizeObserver((entries) => {
  for (const entry of entries) {
    const chart = registry.get(entry.target);
    if (chart) chart.resize();
  }
});

function color(name, fallback) {
  return cssVar(name, fallback);
}

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (ch) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
  ));
}

export function palette() {
  return [
    color('--accent', '#5ad1ff'),
    color('--violet', '#8b93ff'),
    color('--gold', '#f0b35a'),
    color('--up', '#34d399'),
    color('--series-5', '#c084fc'),
    color('--series-6', '#4fd1c5'),
  ];
}

function base() {
  return {
    backgroundColor: 'transparent',
    animation: !window.matchMedia('(prefers-reduced-motion: reduce)').matches,
    textStyle: { fontFamily: FONT, color: C.dim, fontSize: 12 },
    animationDuration: 420,
    animationDurationUpdate: 240,
    animationEasing: 'cubicOut',
  };
}

function tooltip(extra = {}) {
  return {
    trigger: 'axis',
    confine: true,
    backgroundColor: color('--chart-tooltip-bg', 'rgba(8, 14, 24, 0.97)'),
    borderColor: color('--chart-tooltip-border', 'rgba(126, 160, 214, 0.26)'),
    borderWidth: 1,
    padding: [9, 12],
    textStyle: { color: C.text, fontSize: 12.5, fontFamily: FONT },
    axisPointer: {
      type: 'cross',
      lineStyle: { color: color('--chart-pointer', 'rgba(126, 160, 214, 0.35)') },
      crossStyle: { color: color('--chart-pointer', 'rgba(126, 160, 214, 0.35)') },
      label: {
        backgroundColor: color('--chart-axis-label-bg', '#16243a'),
        color: color('--chart-axis-label-text', '#cdd8ea'),
        fontSize: 12,
        fontFamily: FONT,
      },
    },
    extraCssText: `box-shadow: ${color('--chart-tooltip-shadow', '0 18px 44px rgba(0,0,0,.45)')}; border-radius: 10px; backdrop-filter: blur(8px);`,
    ...extra,
  };
}

function legend(extra = {}) {
  return {
    top: 0,
    right: 6,
    icon: 'roundRect',
    itemWidth: 8,
    itemHeight: 8,
    itemGap: 14,
    textStyle: { color: C.mute, fontSize: 12, fontFamily: FONT },
    ...extra,
  };
}

function categoryAxis(data, extra = {}) {
  const { axisLabel, ...rest } = extra;
  return {
    type: 'category',
    data,
    boundaryGap: false,
    axisLine: { lineStyle: { color: C.border } },
    axisTick: { show: false },
    axisLabel: { color: C.mute, fontSize: 12, fontFamily: FONT, hideOverlap: true, ...axisLabel },
    splitLine: { show: false },
    ...rest,
  };
}

function sparseDates(dates, maxLabels = 8) {
  const shortRange = dates.length <= 90;
  return {
    interval: Math.max(0, Math.ceil(dates.length / maxLabels) - 1),
    formatter: (value) => {
      const text = String(value);
      return text.length > 7 ? (shortRange ? text.slice(5, 10) : text.slice(2, 7)) : text;
    },
  };
}

function valueAxis(extra = {}) {
  return {
    type: 'value',
    scale: true,
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: { color: C.mute, fontSize: 12, fontFamily: FONT },
    splitLine: { lineStyle: { color: C.grid, type: [3, 4] } },
    ...extra,
  };
}

function areaGradient(hex, top = 0.22) {
  return {
    type: 'linear',
    x: 0,
    y: 0,
    x2: 0,
    y2: 1,
    colorStops: [
      { offset: 0, color: hexToRgba(hex, top) },
      { offset: 1, color: hexToRgba(hex, 0) },
    ],
  };
}

function barGradient(hex, { strong = 0.66, soft = 0.18, negative = false } = {}) {
  return {
    type: 'linear',
    x: 0,
    y: 0,
    x2: 0,
    y2: 1,
    colorStops: negative
      ? [
          { offset: 0, color: hexToRgba(hex, soft) },
          { offset: 1, color: hexToRgba(hex, strong) },
        ]
      : [
          { offset: 0, color: hexToRgba(hex, strong) },
          { offset: 1, color: hexToRgba(hex, soft) },
        ],
  };
}

function barPoint(value, hex, options = {}) {
  if (!isNum(value)) return null;
  const number = Number(value);
  const negative = number < 0;
  return {
    value: number,
    itemStyle: {
      color: barGradient(hex, { ...options, negative }),
      borderRadius: negative ? [0, 0, 3, 3] : [3, 3, 0, 0],
    },
  };
}

function horizontalBarGradient(hex, { strong = 0.62, soft = 0.2, negative = false } = {}) {
  return {
    type: 'linear',
    x: 0,
    y: 0,
    x2: 1,
    y2: 0,
    colorStops: negative
      ? [
          { offset: 0, color: hexToRgba(hex, strong) },
          { offset: 1, color: hexToRgba(hex, soft) },
        ]
      : [
          { offset: 0, color: hexToRgba(hex, soft) },
          { offset: 1, color: hexToRgba(hex, strong) },
        ],
  };
}

export function create(el, option, { onClick } = {}) {
  if (!el || !window.echarts) return null;
  const previous = registry.get(el);
  if (previous) {
    resizeObserver.unobserve(el);
    previous.dispose();
    live.delete(previous);
    registry.delete(el);
  }
  const chart = window.echarts.init(el, null, { renderer: 'canvas' });
  chart.setOption({ ...base(), ...option }, { notMerge: true });
  if (onClick) chart.on('click', onClick);
  registry.set(el, chart);
  live.add(chart);
  resizeObserver.observe(el);
  return chart;
}

export function replace(el, option, options) {
  return create(el, option, options);
}

export function clear(el) {
  if (!el) return;
  const chart = registry.get(el);
  if (chart) {
    resizeObserver.unobserve(el);
    try {
      chart.dispose();
    } catch {
      /* ignore */
    }
    live.delete(chart);
    registry.delete(el);
  }
  el.innerHTML = '';
}

export function disposeAll() {
  for (const [el, chart] of registry.entries()) {
    resizeObserver.unobserve(el);
    try {
      chart.dispose();
    } catch {
      /* ignore */
    }
  }
  live.clear();
  registry.clear();
}

export function resizeAll() {
  requestAnimationFrame(() => {
    for (const [el, chart] of registry.entries()) {
      if (el.isConnected) chart.resize();
    }
  });
}

export function sparkline(el, values, positive = true) {
  const clean = (values || []).filter(isNum).map(Number);
  if (clean.length < 2) return null;
  const hex = positive ? color('--up', '#34d399') : color('--down', '#f65c6c');
  return create(el, {
    animation: false,
    grid: { left: 0, right: 0, top: 6, bottom: 1 },
    xAxis: { type: 'category', show: false, boundaryGap: false, data: clean.map((_, index) => index) },
    yAxis: { type: 'value', show: false, scale: true },
    series: [
      {
        type: 'line',
        data: clean,
        smooth: 0.35,
        symbol: 'none',
        silent: true,
        lineStyle: { width: 1.5, color: hex },
        areaStyle: { color: areaGradient(hex, 0.18) },
      },
    ],
  });
}

function heatColor(change, alphaFloor = 0.16) {
  const pct = Number(change || 0);
  const base = pct >= 0 ? color('--up', '#34d399') : color('--down', '#f65c6c');
  const strength = Math.min(Math.abs(pct) / 4, 1);
  return hexToRgba(base, alphaFloor + strength * 0.52);
}

export function treemap(el, items, { onSelect } = {}) {
  const points = (items || []).filter((item) => isNum(item.market_cap) && isNum(item.change_pct));
  if (!points.length) return null;
  const totalCap = points.reduce((sum, item) => sum + Math.max(Number(item.market_cap), 1), 0);
  const tileArea = Math.max(el.clientWidth || 0, 1) * Math.max(el.clientHeight || 0, 1);
  const data = points.map((item) => ({
    name: item.symbol,
    value: Math.max(Number(item.market_cap), 1),
    symbol: item.symbol,
    label: item.name,
    change: Number(item.change_pct),
    industry: item.industry,
    cap: Number(item.market_cap),
    share: Math.max(Number(item.market_cap), 1) / (totalCap || 1),
    itemStyle: { color: heatColor(item.change_pct) },
  }));
  return create(
    el,
    {
      animationDuration: 500,
      tooltip: {
        trigger: 'item',
        backgroundColor: color('--chart-tooltip-bg', 'rgba(8, 14, 24, 0.97)'),
        borderColor: color('--chart-tooltip-border', 'rgba(126, 160, 214, 0.26)'),
        borderWidth: 1,
        padding: [9, 12],
        textStyle: { color: C.text, fontSize: 12.5, fontFamily: FONT },
        extraCssText: `box-shadow: ${color('--chart-tooltip-shadow', '0 18px 44px rgba(0,0,0,.45)')}; border-radius: 10px;`,
        formatter: (params) => {
          const item = params.data || {};
          const tone = Number(item.change) >= 0 ? color('--up') : color('--down');
          return `
            <div style="min-width:132px;font-family:${FONT};font-size:12px;line-height:1.8">
              <div style="color:${C.text};font-size:13px;font-weight:600">${esc(item.name)} · ${esc(item.symbol)}</div>
              <div style="color:${C.mute}">${esc(item.label || '')}</div>
              <div style="color:${C.mute}">${esc(item.industry || '行业未分类')}</div>
              <div style="display:flex;justify-content:space-between;gap:18px;margin-top:3px"><span style="color:${C.mute}">涨跌幅</span><span style="color:${tone}">${fmtPct(item.change)}</span></div>
              <div style="display:flex;justify-content:space-between;gap:18px"><span style="color:${C.mute}">总市值</span><span style="color:${C.text}">${fmtCompact(item.cap)}美元</span></div>
            </div>`;
        },
      },
      series: [
        {
          type: 'treemap',
          roam: false,
          nodeClick: false,
          breadcrumb: { show: false },
          width: '100%',
          height: '100%',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          label: {
            show: true,
            position: 'insideTopLeft',
            padding: [7, 5, 0, 6],
            formatter: (params) => {
              const item = params.data || {};
              const sym = String(item.symbol || item.name || '');
              // squarified 布局下格子边长 ≈ √(占比 × 面积)，按可容纳宽度决定标签层级
              const side = Math.sqrt(Math.max(Number(item.share) || 0, 0) * tileArea);
              if (side < sym.length * 7.9 + 14) return '';
              if (side < 62) return `{sym|${sym}}`;
              return `{sym|${sym}}\n{pct|${fmtPct(item.change)}}`;
            },
            rich: {
              sym: { color: color('--chart-tile-text', '#f2f6ff'), fontFamily: FONT, fontSize: 13, fontWeight: 600, lineHeight: 18 },
              pct: { color: color('--chart-tile-sub', 'rgba(240, 246, 255, 0.75)'), fontFamily: FONT, fontSize: 11.5, lineHeight: 16 },
            },
          },
          upperLabel: { show: false },
          itemStyle: { borderColor: color('--chart-gap', '#070d17'), borderWidth: 2, gapWidth: 2 },
          emphasis: { itemStyle: { borderColor: color('--accent', '#5ad1ff'), borderWidth: 2 } },
          levels: [{ itemStyle: { borderWidth: 0, gapWidth: 2 } }],
          data,
        },
      ],
    },
    {
      onClick: (params) => {
        if (onSelect && params?.data?.symbol) onSelect(params.data.symbol);
      },
    },
  );
}

export function normalizedIndexChart(el, sparklines) {
  const entries = Object.entries(sparklines || {}).filter(([, values]) => Array.isArray(values) && values.length > 2);
  if (!entries.length) return null;
  const length = Math.max(...entries.map(([, values]) => values.length));
  const colors = palette();
  const names = { SPX: '标普 500', COMP: '纳指综合', DJIA: '道琼斯', IWM: '罗素 2000' };
  const series = entries.map(([symbol, values], index) => {
    const baseValue = Number(values.find((value) => isNum(value) && Number(value) !== 0) || values[0]);
    const normalized = values.map((value) => (isNum(value) && baseValue ? Number(((Number(value) / baseValue) * 100).toFixed(2)) : null));
    return {
      name: names[symbol] || symbol,
      type: 'line',
      data: normalized,
      smooth: 0.24,
      symbol: 'none',
      lineStyle: { width: 1.8, color: colors[index % colors.length] },
      emphasis: { focus: 'series' },
      ...(index === 0
        ? { markLine: { silent: true, symbol: 'none', label: { show: false }, lineStyle: { color: C.border, type: 'dashed' }, data: [{ yAxis: 100 }] } }
        : {}),
    };
  });
  return create(el, {
    tooltip: tooltip({
      formatter: (params) => {
        const rows = params
          .map(
            (item) =>
              `<div style="display:flex;justify-content:space-between;gap:20px"><span style="color:${item.color}">${esc(item.seriesName)}</span><span>${isNum(item.value) ? Number(item.value).toFixed(2) : '—'}</span></div>`,
          )
          .join('');
        return `<div style="font-family:${FONT};font-size:12px;min-width:150px"><div style="color:${C.mute};margin-bottom:4px">近 ${length} 个交易日 · 归一化</div>${rows}</div>`;
      },
    }),
    legend: legend({ top: 0 }),
    grid: { left: 8, right: 14, top: 30, bottom: 4, containLabel: true },
    xAxis: categoryAxis(Array.from({ length }, (_, index) => index + 1), {
      axisLabel: { show: false },
      axisLine: { show: false },
    }),
    yAxis: valueAxis({
      axisLabel: { color: C.mute, fontSize: 12, fontFamily: FONT, formatter: (value) => Number(value).toFixed(0) },
    }),
    series,
  });
}

export function candles(
  el,
  {
    bars = [],
    indicators = {},
    indicatorParams = null,
    intraday = false,
    range = '1Y',
    interval = null,
    overlays = {},
    legendEl = null,
    zoom = null,
    onZoom = null,
  } = {},
) {
  // Keep one slot per source bar, including gaps: every indicator uses this index.
  const data = Array.isArray(bars) ? Array.from(bars, (bar) => bar || {}) : [];
  if (!el || !data.length) return null;
  // The API may omit the whole object or individual keys: normalize each one independently.
  const indicatorDefaults = {
    ma_periods: [5, 20, 50, 200],
    macd_fast: 12, macd_slow: 26, macd_signal: 9,
    rsi_period: 14, bb_period: 20, bb_mult: 2,
    kc_period: 20, kc_atr_period: 20, kc_mult: 2,
    donchian_period: 20, regression_period: 60, regression_mult: 2,
    vwap_period: 20, vwap_mult: 2,
    adaptive_period: 10, adaptive_fast: 2, adaptive_slow: 30,
    adaptive_atr_period: 14, adaptive_mult: 1.5,
    supertrend_period: 10, supertrend_mult: 3,
    kama_period: 10, kama_fast: 2, kama_slow: 30,
    adx_period: 14, stoch_period: 14, stoch_k: 3, stoch_d: 3,
    cmf_period: 20, atr_period: 14,
    squeeze_bb_period: 20, squeeze_bb_mult: 2,
    squeeze_kc_period: 20, squeeze_kc_mult: 1.5,
    squeeze_momentum_period: 20,
  };
  const rawParams = indicatorParams && typeof indicatorParams === 'object' ? indicatorParams : {};
  const P = { ...indicatorDefaults };
  Object.keys(indicatorDefaults).forEach((key) => {
    if (key === 'ma_periods') return;
    const value = Number(rawParams[key]);
    if (Number.isFinite(value) && value > 0) P[key] = value;
  });
  // Never parseInt the list: periods are array entries, not one scalar.
  const rawPeriods = Array.isArray(rawParams.ma_periods) ? rawParams.ma_periods : [];
  const periods = rawPeriods
    .map((period) => Number(period))
    .filter((period) => Number.isFinite(period) && period > 0);
  P.ma_periods = periods.length ? periods : indicatorDefaults.ma_periods.slice();
  const prefs = {
    ma: true, macd: true, rsi: false, levels: true, log: false,
    channel: 'bb', trend: 'none', study: 'none', ...overlays,
  };
  const up = color('--up', '#34d399');
  const down = color('--down', '#f65c6c');
  const accent = color('--accent', '#5ad1ff');
  const violet = color('--violet', '#8b93ff');
  const gold = color('--gold', '#f0b35a');
  const teal = color('--series-6', '#4fd1c5');
  const width = el.clientWidth || window.innerWidth || 800;
  const mobile = width < 540;
  const logScale = !intraday && Boolean(prefs.log);
  const dates = data.map((bar) => String(bar.t ?? ''));
  const actualInterval = String(interval ?? (intraday ? '1m' : '1d')).toLowerCase();
  const timeInterval = /^(?:\d+(?:s|m|h|min|hour)|intraday|minute|hour|hourly)$/.test(actualInterval);
  const multiSession = new Set(dates.filter(Boolean).map((date) => date.slice(0, 10))).size > 1;
  const labelFormatter = (value) => {
    const text = String(value ?? '');
    const time = text.match(/[T ](\d{2}:\d{2})/);
    if (timeInterval && time) return multiSession ? `${text.slice(5, 10)} ${time[1]}` : time[1];
    if (['3Y', '5Y', 'MAX'].includes(range)) return text.slice(0, 7);
    return text.length >= 10 ? text.slice(5, 10) : text;
  };
  const empty = data.map(() => null);
  const aligned = (values, price = false) => (
    Array.isArray(values) && values.length === data.length
      ? data.map((bar, index) => {
          const value = num(values[index]);
          return isNum(bar.c) && value !== null && (!price || !logScale || value > 0) ? value : null;
        })
      : null
  );
  const maPalette = [gold, accent, violet, color('--series-5', '#c084fc')];
  const maDefs = !intraday && prefs.ma
    ? P.ma_periods.map((period, index) => ({
        name: `MA${period}`,
        color: maPalette[index % maPalette.length],
        values: aligned(indicators?.[`ma${period}`], true),
      })).filter((item) => item.values)
    : [];
  const volMaDefs = !intraday && prefs.ma
    ? [
        { name: 'VMA5', color: gold, values: aligned(indicators?.vol_ma5) },
        { name: 'VMA20', color: accent, values: aligned(indicators?.vol_ma20) },
      ].filter((item) => item.values)
    : [];
  const channelDefs = {
    bb: { name: '布林', color: accent },
    kc: { name: '肯特纳', color: teal },
    donchian: { name: '唐奇安', color: gold },
    regression: { name: '回归', color: violet },
    vwap: { name: '量价', color: teal },
    adaptive: { name: '自适应', color: violet },
  };
  const channelKey = prefs.channel ?? 'bb';
  const channel = !intraday && Object.hasOwn(channelDefs, channelKey)
    ? {
        ...channelDefs[channelKey],
        mid: aligned(indicators?.[channelKey]?.mid, true),
        upper: aligned(indicators?.[channelKey]?.upper, true),
        lower: aligned(indicators?.[channelKey]?.lower, true),
      }
    : null;
  const channelFields = channel ? [
    { name: '中', values: channel.mid },
    { name: '上', values: channel.upper },
    { name: '下', values: channel.lower },
  ] : [];
  const unsignedPct = (value) => fmtPct(value, 2, false);
  const ratio = (value) => fmtNum(value, 2);
  const channelExtras = !channel ? [] : channelKey === 'bb' ? [
    { name: '带宽', values: aligned(indicators?.bb?.width), format: unsignedPct },
    { name: '%B（比值）', values: aligned(indicators?.bb?.percent_b), format: ratio },
  ] : channelKey === 'regression' ? [
    { name: '斜率（价格/期）', values: aligned(indicators?.regression?.slope), format: ratio },
    { name: 'R²', values: aligned(indicators?.regression?.r2), format: ratio },
  ] : channelKey === 'adaptive' ? [
    { name: 'ER（比值）', values: aligned(indicators?.adaptive?.er), format: ratio },
  ] : [];
  const supertrend = !intraday && prefs.trend === 'supertrend' ? {
    up: aligned(indicators?.supertrend?.up, true),
    down: aligned(indicators?.supertrend?.down, true),
    line: aligned(indicators?.supertrend?.line, true),
    direction: aligned(indicators?.supertrend?.direction),
  } : null;
  const kamaValues = !intraday && prefs.trend === 'kama' ? aligned(indicators?.[`kama${P.kama_period}`], true) : null;
  const rsiValues = !intraday && prefs.rsi ? aligned(indicators?.[`rsi${P.rsi_period}`]) : null;
  const macd = !intraday && prefs.macd && indicators?.macd ? {
    dif: aligned(indicators.macd.dif) || empty,
    dea: aligned(indicators.macd.dea) || empty,
    hist: aligned(indicators.macd.hist) || empty,
  } : null;
  const studyDefs = {
    adx: {
      title: `ADX (${P.adx_period})   {b|ADX}  {e|+DI}  {f|−DI}`,
      name: `ADX (${P.adx_period}) · 0–100`, limits: [0, 100], refs: [25],
      fields: [
        { name: 'ADX', raw: indicators?.adx?.adx, color: accent },
        { name: '+DI', raw: indicators?.adx?.plus_di, color: up },
        { name: '−DI', raw: indicators?.adx?.minus_di, color: down },
      ],
    },
    stochastic: {
      title: `Slow Stoch (${P.stoch_period},${P.stoch_k},${P.stoch_d})   {b|K}  {c|D}`,
      name: `Stoch (${P.stoch_period},${P.stoch_k},${P.stoch_d}) · 0–100`, limits: [0, 100], refs: [20, 80],
      fields: [
        { name: 'K', raw: indicators?.stochastic?.k, color: accent },
        { name: 'D', raw: indicators?.stochastic?.d, color: gold },
      ],
    },
    cmf: {
      title: `CMF (${P.cmf_period}) · 比值`, name: `CMF (${P.cmf_period}) · 比值`, refs: [0],
      fields: [{ name: `CMF${P.cmf_period}`, raw: indicators?.[`cmf${P.cmf_period}`], color: teal }],
    },
    obv: {
      title: 'OBV · 累积量（股）', name: 'OBV · 股',
      fields: [{ name: 'OBV', raw: indicators?.obv, color: violet, format: (value) => fmtCompact(value) }],
    },
    atr: {
      title: `ATR% (${P.atr_period}) · 相对收盘价`, name: `ATR% (${P.atr_period})`,
      fields: [{ name: 'ATR%', raw: indicators?.atr_pct, color: gold, format: unsignedPct }],
    },
    squeeze: {
      title: `Squeeze (BB${P.squeeze_bb_period}/KC${P.squeeze_kc_period})   {c|收缩}  {a|未收缩}`,
      name: 'Squeeze · 价格差', refs: [0],
      fields: [{ name: '动能', raw: indicators?.squeeze?.momentum, color: accent }],
    },
  };
  const study = !intraday && Object.hasOwn(studyDefs, prefs.study) ? studyDefs[prefs.study] : null;
  const studyFields = study ? study.fields.map((field) => ({ ...field, values: aligned(field.raw) || empty })) : [];
  const squeezeOn = study && prefs.study === 'squeeze' ? aligned(indicators?.squeeze?.on) || empty : null;

  const trendAt = (index) => {
    if (supertrend) {
      const value = supertrend.line?.[index] ?? supertrend.up?.[index] ?? supertrend.down?.[index];
      const direction = supertrend.direction?.[index];
      const label = direction > 0 ? '上行' : direction < 0 ? '下行' : '';
      return { name: 'Supertrend', value, label, color: direction > 0 ? up : direction < 0 ? down : C.dim };
    }
    return prefs.trend === 'kama' ? { name: `KAMA${P.kama_period}`, value: kamaValues?.[index], label: '', color: gold } : null;
  };
  const changeAt = (index) => {
    const close = num(data[index]?.c);
    const previous = num(data[index - 1]?.c);
    return close !== null && previous !== null && previous !== 0 ? (close / previous - 1) * 100 : null;
  };
  const indexAt = (raw) => {
    if (raw === undefined || raw === null) return -1;
    const byDate = dates.indexOf(String(raw));
    return byDate >= 0 ? byDate : isNum(raw) ? Math.round(Number(raw)) : -1;
  };
  const tooltipIndex = (params) => {
    const items = Array.isArray(params) ? params : params ? [params] : [];
    const item = items.find((entry) => entry.seriesType !== 'custom' && Number.isInteger(entry.dataIndex));
    return item ? item.dataIndex : indexAt(items[0]?.axisValue);
  };
  const legendMetric = (name, text, tint) => (
    `<span class="cl-ma"><i style="background:${esc(tint)}"></i>${esc(name)} <b>${esc(text)}</b></span>`
  );
  const paintLegend = (index, live) => {
    if (!legendEl) return;
    const bar = data[index];
    if (!bar) return;
    const changePct = changeAt(index);
    const toneClass = changePct === null ? 'flat' : changePct > 0 ? 'pos' : changePct < 0 ? 'neg' : 'flat';
    const bits = [`<span class="cl-date">${esc(bar.t ?? '—')}${live ? '' : ' · 最新'}</span>`];
    if (intraday) {
      bits.push(`<span>价 <b>${fmtPrice(bar.c)}</b></span>`);
    } else {
      bits.push(`<span>开 <b>${fmtPrice(bar.o)}</b></span>`);
      bits.push(`<span>高 <b>${fmtPrice(bar.h)}</b></span>`);
      bits.push(`<span>低 <b>${fmtPrice(bar.l)}</b></span>`);
      bits.push(`<span>收 <b>${fmtPrice(bar.c)}</b></span>`);
    }
    bits.push(`<span class="${toneClass}"><b>${fmtPct(changePct)}</b></span>`);
    if (isNum(bar.v)) bits.push(`<span>量 <b>${fmtCompact(bar.v)}</b></span>`);
    if (!intraday) {
      maDefs.forEach((item) => {
        if (isNum(item.values[index])) bits.push(legendMetric(item.name, fmtPrice(item.values[index]), item.color));
      });
      if (channel) {
        const text = channelFields.map((field) => `${field.name} ${fmtPrice(field.values?.[index])}`).join(' / ');
        bits.push(legendMetric(channel.name, text, channel.color));
      }
      const trend = trendAt(index);
      if (trend) bits.push(legendMetric(trend.name, `${trend.label} ${fmtPrice(trend.value)}`.trim(), trend.color));
      if (isNum(rsiValues?.[index])) bits.push(legendMetric(`RSI(${P.rsi_period})`, fmtNum(rsiValues[index], 1), violet));
    }
    legendEl.innerHTML = bits.join('');
  };
  const bindLegend = (chart) => {
    if (!chart || !legendEl) return;
    paintLegend(data.length - 1, false);
    chart.on('updateAxisPointer', (event) => {
      const axis = event?.axesInfo?.find((info) => info.axisDim === 'x') || event?.axesInfo?.[0];
      const index = indexAt(axis?.value);
      if (index >= 0 && index < data.length) paintLegend(index, true);
    });
    chart.on('globalout', () => paintLegend(data.length - 1, false));
  };
  const tooltipRow = (name, text, tint = C.text) => (
    `<div style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap"><span style="color:${esc(C.mute)}">${esc(name)}</span><span style="color:${esc(tint)};overflow-wrap:anywhere">${esc(text)}</span></div>`
  );
  const tooltipBox = (date, rows) => {
    const currentWidth = el.clientWidth || width;
    const small = currentWidth < 540;
    return `<div style="max-width:${Math.max(160, Math.min(currentWidth - 40, small ? 280 : 380))}px;font-family:${FONT};font-size:${small ? 11 : 12}px;line-height:1.65;white-space:normal"><div style="color:${esc(C.mute)};margin-bottom:3px;overflow-wrap:anywhere">${esc(date ?? '—')}</div>${rows.join('')}</div>`;
  };
  const metricText = (fields, index, format = ratio) => fields
    .filter((field) => isNum(field.values?.[index]))
    .map((field) => `${field.name} ${(field.format || format)(field.values[index])}`)
    .join(' · ');

  if (intraday) {
    el.style.height = '450px';
    const values = data.map((bar) => num(bar.c));
    const valid = values.filter(isNum);
    const hex = valid.length && valid[valid.length - 1] < valid[0] ? down : up;
    const chart = create(el, {
      animation: false,
      tooltip: tooltip({
        formatter: (params) => {
          const bar = data[tooltipIndex(params)];
          return bar ? tooltipBox(bar.t, [tooltipRow('价格', fmtPrice(bar.c))]) : '';
        },
      }),
      grid: { left: 8, right: 14, top: 16, bottom: 8, containLabel: true },
      xAxis: categoryAxis(dates, { axisLabel: { fontSize: mobile ? 10 : 11.5, formatter: labelFormatter }, boundaryGap: false }),
      yAxis: valueAxis({ axisLabel: { color: C.mute, fontSize: 12, fontFamily: FONT, formatter: (value) => fmtPrice(value) } }),
      series: [{
        name: '价格', type: 'line', data: values, smooth: 0.15, symbol: 'none', connectNulls: false,
        lineStyle: { width: 1.7, color: hex }, areaStyle: { color: areaGradient(hex, 0.16) },
      }],
    });
    bindLegend(chart);
    return chart;
  }

  const candleData = data.map((bar) => {
    const values = [bar.o, bar.c, bar.l, bar.h].map(num);
    return values.every((value) => value !== null && (!logScale || value > 0)) ? values : [null, null, null, null];
  });
  const lastClose = num(data[data.length - 1]?.c);
  const keyLevels = (() => {
    if (!prefs.levels || !lastClose) return [];
    const tail = data.slice(-180);
    const pivotValues = [];
    for (let index = 3; index < tail.length - 3; index += 1) {
      const high = num(tail[index]?.h);
      const low = num(tail[index]?.l);
      if (high === null || low === null) continue;
      const window = tail.slice(index - 3, index + 4);
      if (window.every((bar) => num(bar?.h) !== null && Number(bar.h) <= high)) pivotValues.push({ value: high, side: 'resistance' });
      if (window.every((bar) => num(bar?.l) !== null && Number(bar.l) >= low)) pivotValues.push({ value: low, side: 'support' });
    }
    const tolerance = lastClose * 0.004;
    const merged = [];
    pivotValues
      .filter((item) => Number.isFinite(item.value) && Math.abs(item.value / lastClose - 1) <= 0.1)
      .sort((a, b) => a.value - b.value)
      .forEach((item) => {
        const last = merged[merged.length - 1];
        if (last && Math.abs(item.value - last.value) <= tolerance) {
          last.value = (last.value + item.value) / 2;
        } else {
          merged.push({ ...item });
        }
      });
    const supports = merged.filter((item) => item.value < lastClose * 0.997).sort((a, b) => b.value - a.value).slice(0, 2)
      .map((item, index) => ({ ...item, side: 'support', label: `S${index + 1}` }));
    const resistances = merged.filter((item) => item.value > lastClose * 1.003).sort((a, b) => a.value - b.value).slice(0, 2)
      .map((item, index) => ({ ...item, side: 'resistance', label: `R${index + 1}` }));
    return [...supports, ...resistances];
  })();
  const volumeData = data.map((bar) => ({
    value: isNum(bar.c) ? num(bar.v) : null,
    itemStyle: { color: isNum(bar.o) && isNum(bar.c) ? (Number(bar.c) >= Number(bar.o) ? up : down) : C.mute, opacity: 0.45 },
  }));
  // Fixed shared margins, not containLabel: large OBV/volume labels cannot shift x pixels.
  const plotLeft = mobile ? 12 : 18;
  const plotRight = mobile ? 58 : 70;
  const grids = [];
  const titles = [];
  const yAxes = [];
  let cursor = 22;
  const compactAxis = (value) => fmtCompact(value, mobile ? 0 : 1);
  const priceAxis = (value) => Math.abs(Number(value)) >= 100000 ? compactAxis(value) : fmtPrice(value);
  const addPane = (height, title, formatter, extra = {}) => {
    const index = grids.length;
    grids.push({ left: plotLeft, right: plotRight, top: cursor, height, containLabel: false });
    titles.push({
      text: title, left: plotLeft, top: cursor - 20, padding: 0,
      textStyle: {
        color: C.dim, fontSize: mobile ? 10 : 11, fontFamily: FONT, fontWeight: 500,
        width: Math.max(160, width - plotLeft - plotRight), overflow: 'truncate',
        rich: { a: { color: C.mute }, b: { color: accent }, c: { color: gold }, d: { color: violet }, e: { color: up }, f: { color: down } },
      },
    });
    yAxes.push(valueAxis({
      gridIndex: index, position: 'right', splitNumber: index === 0 ? 4 : 2,
      axisLabel: {
        color: C.mute, fontSize: mobile ? 10 : 11, fontFamily: FONT,
        width: plotRight - 10, overflow: 'truncate', margin: 8, hideOverlap: true, formatter,
      },
      axisPointer: { label: { formatter: (params) => formatter(params.value) } },
      ...extra,
    }));
    cursor += height + 32;
    return index;
  };
  const mainTitle = ['价格', logScale ? '对数' : '', channel?.name, supertrend ? 'Supertrend' : kamaValues ? `KAMA${P.kama_period}` : '', maDefs.length ? 'MA' : ''].filter(Boolean).join(' · ');
  addPane(330, mainTitle, priceAxis);
  addPane(65, `成交量 · 股${volMaDefs.length ? '   {c|VMA5}  {b|VMA20}' : ''}`, compactAxis, { min: 0, splitLine: { show: false } });
  const macdGrid = macd ? addPane(110, `MACD (${P.macd_fast},${P.macd_slow},${P.macd_signal})   {b|DIF}  {c|DEA} · 柱×2`, compactAxis, { scale: false }) : -1;
  const rsiGrid = rsiValues ? addPane(110, `RSI(${P.rsi_period}) · 30 / 70`, (value) => fmtNum(value, 0), { min: 0, max: 100 }) : -1;
  const studyGrid = study ? addPane(110, study.title,
    prefs.study === 'atr' ? (value) => fmtPct(value, 1, false) : ['adx', 'stochastic'].includes(prefs.study) ? (value) => fmtNum(value, 0) : prefs.study === 'cmf' ? ratio : compactAxis,
    study.limits ? { min: study.limits[0], max: study.limits[1] } : prefs.study === 'atr' ? { min: 0 } : { scale: prefs.study === 'obv' },
  ) : -1;
  // Last pane's labels, a gap, and the slider all have their own vertical space.
  el.style.height = `${cursor - 32 + 60}px`;
  if (logScale) {
    yAxes[0] = {
      ...yAxes[0], type: 'log', logBase: 10,
      min: ({ min }) => isNum(min) && min > 0 ? min * 0.98 : 0.98,
      max: ({ max }) => isNum(max) && max > 0 ? max * 1.02 : 1.02,
    };
  }
  const xAxes = grids.map((_, index) => categoryAxis(dates, {
    gridIndex: index, boundaryGap: true,
    axisLabel: index === grids.length - 1 ? { fontSize: mobile ? 10 : 11.5, formatter: labelFormatter, hideOverlap: true } : { show: false },
    axisLine: index === grids.length - 1 ? { lineStyle: { color: C.border } } : { show: false },
    axisPointer: { show: true, snap: true, label: { show: index === grids.length - 1 } },
  }));
  const referenceLines = (values, showLabel = true) => ({
    silent: true, symbol: 'none',
    label: { show: showLabel, color: C.mute, fontSize: 9, fontFamily: FONT, position: 'insideEndTop' },
    lineStyle: { color: C.mute, opacity: 0.45, type: 'dashed' },
    data: values.map((value) => ({ yAxis: value })),
  });
  const series = [{
    name: 'K线', type: 'candlestick', data: candleData, xAxisIndex: 0, yAxisIndex: 0, z: 3,
    itemStyle: {
      color: hexToRgba(up, 0.86), color0: hexToRgba(down, 0.86),
      borderColor: up, borderColor0: down, borderWidth: 1.1,
    },
    emphasis: { itemStyle: { borderWidth: 1.4 } },
    markLine: {
      silent: true,
      symbol: 'none',
      data: [
        ...keyLevels.map((item) => ({
          yAxis: item.value,
          label: {
            show: item.label.endsWith('1'),
            position: item.side === 'support' ? 'insideStartBottom' : 'insideStartTop',
            formatter: `${item.label} ${fmtPrice(item.value)}`,
            color: item.side === 'support' ? up : down,
            fontSize: 9.5,
            fontFamily: FONT,
            padding: [1, 3],
          },
          lineStyle: {
            color: item.side === 'support' ? up : down,
            opacity: 0.32,
            width: 0.9,
            type: [4, 4],
          },
        })),
        ...(lastClose !== null ? [{
          yAxis: lastClose,
          label: {
            show: true,
            position: 'insideEndTop',
            formatter: fmtPrice(lastClose),
            color: color('--panel', '#fff'),
            backgroundColor: lastClose >= Number(data[data.length - 2]?.c) ? up : down,
            padding: [2, 5],
            borderRadius: 3,
            fontSize: 10,
            fontWeight: 600,
            fontFamily: FONT,
          },
          lineStyle: {
            color: lastClose >= Number(data[data.length - 2]?.c) ? up : down,
            opacity: 0.55,
            width: 1,
            type: [2, 3],
          },
        }] : []),
      ],
    },
  }];
  const addLine = (name, values, grid, tint, extra = {}) => {
    if (!values) return;
    const { lineStyle, ...rest } = extra;
    series.push({
      name, type: 'line', data: values, xAxisIndex: grid, yAxisIndex: grid,
      smooth: false, symbol: 'none', connectNulls: false, clip: true,
      itemStyle: { color: tint }, lineStyle: { width: 1.2, color: tint, opacity: 0.9, ...lineStyle },
      ...rest,
    });
  };
  if (channel) {
    if (channel.upper && channel.lower) {
      series.push({
        name: `${channel.name} 区间`, type: 'custom', coordinateSystem: 'cartesian2d',
        xAxisIndex: 0, yAxisIndex: 0, z: 1, clip: true, silent: true, progressive: 0,
        tooltip: { show: false }, emphasis: { disabled: true },
        dimensions: ['x', 'upper', 'lower', 'previousX', 'previousUpper', 'previousLower'],
        encode: { x: [0, 3], y: [1, 2, 4, 5], tooltip: [] },
        // Rolling endpoints are used as delivered, never a regression refit over visible bars.
        data: data.map((_, index) => [
          index, channel.upper[index], channel.lower[index],
          index > 0 ? index - 1 : null,
          index > 0 ? channel.upper[index - 1] : null,
          index > 0 ? channel.lower[index - 1] : null,
        ]),
        renderItem: (params, api) => {
          const x = api.value(0);
          const upper = api.value(1);
          const lower = api.value(2);
          const previousX = api.value(3);
          const previousUpper = api.value(4);
          const previousLower = api.value(5);
          const bounds = [upper, lower, previousUpper, previousLower];
          if (!Number.isFinite(x) || !Number.isFinite(previousX) || previousX !== x - 1
            || !bounds.every((value) => Number.isFinite(value) && (!logScale || value > 0))
            || upper < lower || previousUpper < previousLower) return null;
          // Transform each boundary independently, so log axes never use stacked distances.
          const points = [
            api.coord([previousX, previousUpper]), api.coord([x, upper]),
            api.coord([x, lower]), api.coord([previousX, previousLower]),
          ];
          if (!points.every((point) => point.every(Number.isFinite))) return null;
          return { type: 'polygon', silent: true, shape: { points }, style: { fill: channel.color, opacity: 0.07 } };
        },
      });
    }
    addLine(`${channel.name} 中轨`, channel.mid, 0, channel.color, { z: 2, lineStyle: { width: 1.1 } });
    addLine(`${channel.name} 上轨`, channel.upper, 0, channel.color, { z: 2, lineStyle: { width: 0.8, opacity: 0.65 } });
    addLine(`${channel.name} 下轨`, channel.lower, 0, channel.color, { z: 2, lineStyle: { width: 0.8, opacity: 0.65 } });
  }
  maDefs.forEach((item) => addLine(item.name, item.values, 0, item.color, { z: 4, lineStyle: { width: 1.1, opacity: 0.85 } }));
  if (supertrend) {
    addLine('Supertrend 上行', supertrend.up, 0, up, { z: 5, lineStyle: { width: 1.7 } });
    addLine('Supertrend 下行', supertrend.down, 0, down, { z: 5, lineStyle: { width: 1.7 } });
  }
  addLine(`KAMA${P.kama_period}`, kamaValues, 0, gold, { z: 5, lineStyle: { width: 1.6 } });
  series.push({
    name: '成交量', type: 'bar', data: volumeData, xAxisIndex: 1, yAxisIndex: 1,
    barWidth: '62%', itemStyle: { borderRadius: [1, 1, 0, 0] },
  });
  volMaDefs.forEach((item) => addLine(item.name, item.values, 1, item.color, { lineStyle: { width: 0.9, opacity: 0.65 } }));
  if (macd) {
    series.push({
      name: 'MACD', type: 'bar',
      // The API histogram already is 2 * (DIF - DEA).
      data: macd.hist.map((value) => ({ value, itemStyle: { color: value === null ? C.mute : value >= 0 ? up : down, opacity: 0.6 } })),
      xAxisIndex: macdGrid, yAxisIndex: macdGrid, barWidth: '55%', markLine: referenceLines([0], false),
    });
    addLine('DIF', macd.dif, macdGrid, accent);
    addLine('DEA', macd.dea, macdGrid, gold);
  }
  if (rsiValues) addLine(`RSI(${P.rsi_period})`, rsiValues, rsiGrid, violet, { markLine: referenceLines([30, 70]) });
  if (study) {
    if (prefs.study === 'squeeze') {
      const momentum = studyFields[0].values;
      series.push({
        name: 'Squeeze momentum', type: 'bar', xAxisIndex: studyGrid, yAxisIndex: studyGrid, barWidth: '60%',
        data: momentum.map((value, index) => {
          const previous = momentum[index - 1];
          const strengthening = isNum(previous) && (value >= 0 ? value > previous : value < previous);
          return { value, itemStyle: { color: value === null ? C.mute : value >= 0 ? up : down, opacity: strengthening ? 0.85 : 0.45 } };
        }),
        markLine: referenceLines([0], false),
      }, {
        name: 'Squeeze 状态（非信号）', type: 'scatter', xAxisIndex: studyGrid, yAxisIndex: studyGrid,
        symbolSize: mobile ? 4 : 5, z: 4, encode: { x: 0, y: 1 },
        data: squeezeOn.map((state, index) => ({
          value: [index, state === 0 || state === 1 ? 0 : null],
          itemStyle: { color: state === 1 ? gold : C.mute, opacity: state === 1 ? 1 : 0.75 },
        })),
      });
    } else {
      studyFields.forEach((field, index) => addLine(field.name, field.values, studyGrid, field.color, {
        ...(index === 0 && study.refs ? { markLine: referenceLines(study.refs, prefs.study !== 'cmf') } : {}),
        ...(prefs.study === 'cmf' ? { areaStyle: { color: teal, opacity: 0.12, origin: 0 } } : {}),
      }));
    }
  }
  const defaultStart = ['3Y', '5Y', 'MAX'].includes(range) ? 45 : 0;
  const clampZoom = (value) => Math.max(0, Math.min(100, Number(value)));
  let zoomState = {
    start: isNum(zoom?.start) ? clampZoom(zoom.start) : defaultStart,
    end: isNum(zoom?.end) ? clampZoom(zoom.end) : 100,
  };
  if (zoomState.start > zoomState.end) zoomState = { start: zoomState.end, end: zoomState.start };
  const zoomAxes = grids.map((_, index) => index);
  const chart = create(el, {
    animation: false,
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    tooltip: tooltip({
      formatter: (params) => {
        const index = tooltipIndex(params);
        const bar = data[index];
        if (!bar) return '';
        const changePct = changeAt(index);
        const tone = changePct === null || changePct === 0 ? C.dim : changePct > 0 ? up : down;
        const rows = [
          tooltipRow('开盘 / 收盘', `${fmtPrice(bar.o)} / ${fmtPrice(bar.c)}`),
          tooltipRow('最高 / 最低', `${fmtPrice(bar.h)} / ${fmtPrice(bar.l)}`),
          tooltipRow('涨跌幅', fmtPct(changePct), tone),
        ];
        if (isNum(bar.v)) rows.push(tooltipRow('成交量', `${fmtCompact(bar.v)} 股`));
        if (channel) {
          const text = metricText(channelFields, index, fmtPrice);
          if (text) rows.push(tooltipRow(`${channel.name} · 价格`, text, channel.color));
          const extras = metricText(channelExtras, index);
          if (extras) rows.push(tooltipRow('通道统计', extras));
        }
        const trend = trendAt(index);
        if (trend && isNum(trend.value)) rows.push(tooltipRow(`${trend.name} · 价格`, `${trend.label} ${fmtPrice(trend.value)}`.trim(), trend.color));
        if (macd) {
          const text = metricText([
            { name: 'DIF', values: macd.dif }, { name: 'DEA', values: macd.dea }, { name: '柱', values: macd.hist },
          ], index);
          if (text) rows.push(tooltipRow('MACD · 价格差', text));
        }
        if (isNum(rsiValues?.[index])) rows.push(tooltipRow(`RSI(${P.rsi_period})`, `${fmtNum(rsiValues[index], 1)} / 100`, violet));
        if (study) {
          let text = metricText(studyFields, index);
          const state = squeezeOn?.[index];
          if (state === 0 || state === 1) text += `${text ? ' · ' : ''}${state === 1 ? '收缩中' : '未收缩'}`;
          if (text) rows.push(tooltipRow(study.name, text));
        }
        return tooltipBox(bar.t, rows);
      },
    }),
    title: titles,
    grid: grids,
    xAxis: xAxes,
    yAxis: yAxes,
    dataZoom: [{
      type: 'inside', xAxisIndex: zoomAxes, filterMode: 'none', ...zoomState,
      zoomOnMouseWheel: 'ctrl', moveOnMouseMove: true, moveOnMouseWheel: false,
    }, {
      type: 'slider', xAxisIndex: zoomAxes, filterMode: 'none', ...zoomState,
      left: plotLeft, right: plotRight, bottom: 6, height: 20,
      showDataShadow: false, brushSelect: false, showDetail: !mobile,
      borderColor: C.border, backgroundColor: C.grid, fillerColor: hexToRgba(accent, 0.12),
      handleStyle: { color: accent, borderColor: accent },
      textStyle: { color: C.mute, fontSize: 10, fontFamily: FONT },
      labelFormatter: (value, valueStr) => labelFormatter(valueStr ?? dates[Math.round(value)] ?? ''),
    }],
    series,
  });
  bindLegend(chart);
  if (chart && typeof onZoom === 'function') {
    chart.on('datazoom', (event) => {
      const update = event?.batch?.[0] || event || {};
      const current = chart.getOption().dataZoom?.[0] || {};
      zoomState = {
        start: clampZoom(isNum(update.start) ? update.start : isNum(current.start) ? current.start : zoomState.start),
        end: clampZoom(isNum(update.end) ? update.end : isNum(current.end) ? current.end : zoomState.end),
      };
      onZoom({ ...zoomState });
    });
  }
  return chart;
}

export function exportPNG(el, filename = 'starmap-chart.png') {
  const chart = registry.get(el);
  if (!chart) return false;
  const url = chart.getDataURL({
    type: 'png',
    pixelRatio: 2,
    backgroundColor: cssVar('--panel', '#0b1320'),
  });
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  return true;
}

export function financialsChart(el, rows, mode = 'annual') {
  const list = (rows || [])
    .filter((row) => isNum(row.revenue) || isNum(row.net_profit))
    .slice()
    .reverse();
  if (!list.length) return null;
  const accent = color('--accent', '#5ad1ff');
  const violet = color('--violet', '#8b93ff');
  const teal = color('--series-6', '#4fd1c5');
  const up = color('--up', '#34d399');
  const down = color('--down', '#f65c6c');
  const gold = color('--gold', '#f0b35a');
  const dates = list.map((row) => row.date);
  const labelFormatter = (value) => (mode === 'annual' ? String(value).slice(2, 4) + '\'' : String(value).slice(5));
  return create(el, {
    tooltip: tooltip({
      formatter: (params) => {
        const index = params?.[0]?.dataIndex;
        const row = list[index];
        if (!row) return '';
        const item = (label, value, tone = C.text, suffix = '') =>
          `<div style="display:flex;justify-content:space-between;gap:22px"><span style="color:${C.mute}">${label}</span><span style="color:${tone}">${value}${suffix}</span></div>`;
        return `<div style="min-width:178px;font-family:${FONT};font-size:12px;line-height:1.8">
          <div style="color:${C.mute};margin-bottom:3px">${row.date} · ${mode === 'annual' ? '年报' : '季报'}</div>
          ${item('营收', isNum(row.revenue) ? fmtCompact(row.revenue) + '美元' : '—')}
          ${item('净利润', isNum(row.net_profit) ? fmtCompact(row.net_profit) + '美元' : '—', Number(row.net_profit) >= 0 ? up : color('--down'))}
          ${item('毛利率', isNum(row.gross_margin) ? Number(row.gross_margin).toFixed(1) : '—', C.dim, '%')}
          ${item('净利率', isNum(row.net_margin) ? Number(row.net_margin).toFixed(1) : '—', C.dim, '%')}
          ${item('营收同比', isNum(row.revenue_yoy) ? fmtPct(row.revenue_yoy, 1) : '—', Number(row.revenue_yoy) >= 0 ? up : color('--down'))}
        </div>`;
      },
    }),
    legend: legend({ data: ['营收', '净利润', '毛利率', '净利率'] }),
    grid: { left: 12, right: 18, top: 38, bottom: 10, containLabel: true },
    xAxis: categoryAxis(dates, {
      boundaryGap: true,
      axisLabel: { color: C.mute, fontSize: 11.5, fontFamily: FONT, formatter: labelFormatter },
    }),
    yAxis: [
      valueAxis({
        name: '十亿美元',
        nameTextStyle: { color: C.mute, fontSize: 10, padding: [0, 0, 0, 0] },
        axisLabel: { color: C.mute, fontSize: 11.5, fontFamily: FONT, formatter: (value) => fmtNum(value, 0) },
      }),
      valueAxis({
        name: '%',
        nameTextStyle: { color: C.mute, fontSize: 10 },
        axisLabel: { color: C.mute, fontSize: 11.5, fontFamily: FONT, formatter: (value) => `${value}` },
        splitLine: { show: false },
      }),
    ],
    series: [
      {
        name: '营收',
        type: 'bar',
        data: list.map((row) => {
          const value = isNum(row.revenue) ? Number(row.revenue) / 1e9 : null;
          return barPoint(value, isNum(value) && value < 0 ? down : accent);
        }),
        barMaxWidth: 18,
        barGap: '22%',
        barCategoryGap: '38%',
        itemStyle: { color: accent },
      },
      {
        name: '净利润',
        type: 'bar',
        data: list.map((row) => {
          const value = isNum(row.net_profit) ? Number(row.net_profit) / 1e9 : null;
          return barPoint(value, isNum(value) && value < 0 ? down : violet);
        }),
        barMaxWidth: 18,
        itemStyle: { color: violet },
      },
      {
        name: '毛利率',
        type: 'line',
        yAxisIndex: 1,
        data: list.map((row) => num(row.gross_margin)),
        smooth: 0.2,
        symbol: 'circle',
        symbolSize: 3.5,
        lineStyle: { width: 1.35, color: gold },
        itemStyle: { color: gold },
      },
      {
        name: '净利率',
        type: 'line',
        yAxisIndex: 1,
        data: list.map((row) => num(row.net_margin)),
        smooth: 0.2,
        symbol: 'circle',
        symbolSize: 3.5,
        lineStyle: { width: 1.35, color: teal },
        itemStyle: { color: teal },
      },
    ],
  });
}

export function cashflowChart(el, items) {
  const list = (items || []).filter((item) => isNum(item.ocf) || isNum(item.fcf)).slice();
  if (!list.length) return null;
  const accent = color('--accent', '#5ad1ff');
  const teal = color('--series-6', '#4fd1c5');
  const down = color('--down', '#f65c6c');
  const dates = list.map((item) => item.date);
  return create(el, {
    tooltip: tooltip({
      formatter: (params) => {
        const index = params?.[0]?.dataIndex;
        const row = list[index];
        if (!row) return '';
        const line = (label, value, tone = C.text) =>
          `<div style="display:flex;justify-content:space-between;gap:22px"><span style="color:${C.mute}">${label}</span><span style="color:${tone}">${isNum(value) ? fmtCompact(value) + '美元' : '—'}</span></div>`;
        return `<div style="min-width:184px;font-family:${FONT};font-size:12px;line-height:1.8">
          <div style="color:${C.mute};margin-bottom:3px">${row.date} · SEC 10-K</div>
          ${line('经营现金流', row.ocf, teal)}
          ${line('资本开支', row.capex, down)}
          ${line('自由现金流', row.fcf, accent)}
        </div>`;
      },
    }),
    legend: legend({ data: ['经营现金流', '资本开支', '自由现金流'] }),
    grid: { left: 12, right: 18, top: 38, bottom: 10, containLabel: true },
    xAxis: categoryAxis(dates, {
      boundaryGap: true,
      axisLabel: { color: C.mute, fontSize: 11.5, fontFamily: FONT, formatter: (value) => String(value).slice(0, 4) },
    }),
    yAxis: valueAxis({
      name: '十亿美元',
      nameTextStyle: { color: C.mute, fontSize: 10 },
      axisLabel: { color: C.mute, fontSize: 11.5, fontFamily: FONT, formatter: (value) => fmtNum(value, 0) },
    }),
    series: [
      {
        name: '经营现金流',
        type: 'bar',
        data: list.map((item) => {
          const value = isNum(item.ocf) ? Number(item.ocf) / 1e9 : null;
          return barPoint(value, isNum(value) && value < 0 ? down : teal);
        }),
        barMaxWidth: 18,
        barGap: '26%',
        barCategoryGap: '38%',
        itemStyle: { color: teal },
      },
      {
        name: '资本开支',
        type: 'bar',
        data: list.map((item) => {
          const value = isNum(item.capex) ? -Math.abs(Number(item.capex)) / 1e9 : null;
          return barPoint(value, down);
        }),
        barMaxWidth: 18,
        itemStyle: { color: down },
      },
      {
        name: '自由现金流',
        type: 'line',
        data: list.map((item) => (isNum(item.fcf) ? Number(item.fcf) / 1e9 : null)),
        smooth: 0.2,
        symbol: 'circle',
        symbolSize: 3.5,
        lineStyle: { width: 1.5, color: accent },
        itemStyle: { color: accent },
      },
    ],
  });
}

export function earningsQualityChart(el, rows, ratios, mode = 'annual') {
  const ratioMap = new Map((ratios || []).map((item) => [item.date, item]));
  const list = (rows || []).filter((row) => isNum(row.net_income) || isNum(row.ocf)).slice();
  if (!list.length) return null;
  const violet = color('--violet', '#8b93ff');
  const teal = color('--series-6', '#4fd1c5');
  const down = color('--down', '#f65c6c');
  const gold = color('--gold', '#f0b35a');
  const dates = list.map((row) => row.date);
  const label = (value) => (mode === 'annual' ? `${String(value).slice(2, 4)}'` : String(value).slice(2, 7));
  const ratio = (date, key) => ratioMap.get(date)?.[key] ?? null;
  return create(el, {
    tooltip: tooltip({
      formatter: (params) => {
        const index = params?.[0]?.dataIndex;
        const row = list[index];
        if (!row) return '';
        const r = ratioMap.get(row.date) || {};
        const line = (name, value, tone = C.text) =>
          `<div style="display:flex;justify-content:space-between;gap:22px"><span style="color:${C.mute}">${name}</span><span style="color:${tone}">${value}</span></div>`;
        return `<div style="min-width:186px;font-family:${FONT};font-size:12px;line-height:1.8">
          <div style="color:${C.mute};margin-bottom:3px">${row.date} · SEC XBRL</div>
          ${line('净利润', isNum(row.net_income) ? `${fmtCompact(row.net_income)}美元` : '—', violet)}
          ${line('经营现金流', isNum(row.ocf) ? `${fmtCompact(row.ocf)}美元` : '—', teal)}
          ${line('现金转化 OCF/NI', isNum(r.ocf_to_ni) ? `${Number(r.ocf_to_ni).toFixed(2)}x` : '—', teal)}
          ${line('应计比率', isNum(r.accrual_ratio) ? `${Number(r.accrual_ratio).toFixed(1)}%` : '—', gold)}
          ${line('ROE', isNum(r.roe) ? `${Number(r.roe).toFixed(1)}%` : '—', C.dim)}
        </div>`;
      },
    }),
    legend: legend({ data: ['净利润', '现金转化', '应计比率'] }),
    grid: { left: 12, right: 18, top: 38, bottom: 10, containLabel: true },
    xAxis: categoryAxis(dates, {
      boundaryGap: true,
      axisLabel: { color: C.mute, fontSize: 11.5, fontFamily: FONT, formatter: label },
    }),
    yAxis: [
      valueAxis({
        name: '十亿美元',
        nameTextStyle: { color: C.mute, fontSize: 10 },
        axisLabel: { color: C.mute, fontSize: 11.5, fontFamily: FONT, formatter: (value) => fmtNum(value, 0) },
      }),
      valueAxis({
        name: '%',
        nameTextStyle: { color: C.mute, fontSize: 10 },
        axisLabel: { color: C.mute, fontSize: 11.5, fontFamily: FONT, formatter: (value) => `${value}` },
        splitLine: { show: false },
      }),
    ],
    series: [
      {
        name: '净利润',
        type: 'bar',
        data: list.map((row) => {
          const value = isNum(row.net_income) ? Number(row.net_income) / 1e9 : null;
          return barPoint(value, isNum(value) && value < 0 ? down : violet);
        }),
        barMaxWidth: 18,
        barCategoryGap: '42%',
        itemStyle: { color: violet },
      },
      {
        name: '现金转化',
        type: 'line',
        yAxisIndex: 1,
        data: list.map((row) => {
          const value = ratio(row.date, 'ocf_to_ni');
          return isNum(value) ? Number(value) * 100 : null;
        }),
        smooth: 0.2,
        symbol: 'circle',
        symbolSize: 3.5,
        lineStyle: { width: 1.4, color: teal },
        itemStyle: { color: teal },
      },
      {
        name: '应计比率',
        type: 'line',
        yAxisIndex: 1,
        data: list.map((row) => {
          const value = ratio(row.date, 'accrual_ratio');
          return isNum(value) ? Number(value) : null;
        }),
        smooth: 0.2,
        symbol: 'circle',
        symbolSize: 3.5,
        lineStyle: { width: 1.4, color: gold, type: 'dashed' },
        itemStyle: { color: gold },
      },
    ],
  });
}

export function performanceChart(el, { dates = [], series = {}, benchmarkName = '基准', labels = {} }) {
  const keys = Object.keys(series || {}).filter((key) => Array.isArray(series[key]) && series[key].length);
  if (!dates.length || !keys.length) return null;
  const colors = palette();
  const ticks = sparseDates(dates, Math.min(8, Math.max(3, Math.floor(el.clientWidth / 80))));
  const solo = keys.filter((key) => key !== 'benchmark').length === 1;
  return create(el, {
    tooltip: tooltip({
      formatter: (params) => {
        const date = params?.[0]?.axisValueLabel || params?.[0]?.axisValue || '';
        const rows = params
          .map(
            (item) =>
              `<div style="display:flex;justify-content:space-between;gap:22px"><span style="color:${item.color}">${esc(item.seriesName)}</span><span>${isNum(item.value) ? Number(item.value).toFixed(2) : '—'}</span></div>`,
          )
          .join('');
        return `<div style="font-family:${FONT};font-size:12px;min-width:164px"><div style="color:${C.mute};margin-bottom:4px">${esc(date)}</div>${rows}</div>`;
      },
    }),
    legend: legend({ data: keys.map((key) => labels[key] || key) }),
    grid: { left: 8, right: 14, top: 32, bottom: 4, containLabel: true },
    xAxis: categoryAxis(dates, {
      axisLabel: { color: C.mute, fontSize: 11.5, fontFamily: FONT, ...ticks },
    }),
    yAxis: valueAxis({
      scale: true,
      axisLabel: { color: C.mute, fontSize: 11.5, fontFamily: FONT, formatter: (value) => Number(value).toFixed(0) },
    }),
    series: keys.map((key, index) => {
      const isBenchmark = key === 'benchmark';
      const hex = isBenchmark ? C.mute : colors[index % colors.length];
      return {
        name: labels[key] || key,
        type: 'line',
        data: series[key],
        smooth: 0.18,
        smoothMonotone: 'x',
        symbol: 'none',
        connectNulls: false,
        sampling: series[key].length > 600 ? 'lttb' : undefined,
        lineStyle: {
          width: isBenchmark ? 1.2 : 1.8,
          color: isBenchmark ? C.mute : hex,
          type: isBenchmark ? 'dashed' : 'solid',
        },
        itemStyle: { color: isBenchmark ? C.mute : hex },
        areaStyle: solo && !isBenchmark ? { color: areaGradient(hex, 0.12) } : undefined,
        emphasis: { focus: 'series' },
      };
    }),
  });
}

export function drawdownChart(el, { dates = [], series = {}, labels = {} }) {
  const keys = Object.keys(series || {}).filter((key) => Array.isArray(series[key]) && series[key].length);
  if (!dates.length || !keys.length) return null;
  const colors = palette();
  const ticks = sparseDates(dates, Math.min(8, Math.max(3, Math.floor(el.clientWidth / 80))));
  return create(el, {
    tooltip: tooltip({
      formatter: (params) => {
        const date = params?.[0]?.axisValueLabel || params?.[0]?.axisValue || '';
        const rows = params
          .map(
            (item) =>
              `<div style="display:flex;justify-content:space-between;gap:22px"><span style="color:${item.color}">${esc(item.seriesName)}</span><span>${isNum(item.value) ? `${Number(item.value).toFixed(2)}%` : '—'}</span></div>`,
          )
          .join('');
        return `<div style="font-family:${FONT};font-size:12px;min-width:164px"><div style="color:${C.mute};margin-bottom:4px">${esc(date)} · 回撤</div>${rows}</div>`;
      },
    }),
    legend: legend({ data: keys.map((key) => labels[key] || key) }),
    grid: { left: 8, right: 14, top: 30, bottom: 4, containLabel: true },
    xAxis: categoryAxis(dates, {
      axisLabel: { color: C.mute, fontSize: 11.5, fontFamily: FONT, ...ticks },
    }),
    yAxis: valueAxis({
      max: 0,
      min: (value) => Math.min(-1, Math.floor((value.min || 0) * 1.15)),
      axisLabel: { color: C.mute, fontSize: 11.5, fontFamily: FONT, formatter: (value) => `${Number(value).toFixed(0)}%` },
    }),
    series: keys.map((key, index) => {
      const isBenchmark = key === 'benchmark';
      const hex = isBenchmark ? C.mute : colors[index % colors.length];
      return {
        name: labels[key] || key,
        type: 'line',
        data: series[key],
        smooth: false,
        symbol: 'none',
        connectNulls: false,
        sampling: series[key].length > 600 ? 'lttb' : undefined,
        lineStyle: { width: isBenchmark ? 1.2 : 1.5, color: hex, type: isBenchmark ? 'dashed' : 'solid' },
        itemStyle: { color: hex },
        areaStyle: isBenchmark ? undefined : { color: areaGradient(hex, 0.10) },
        emphasis: { focus: 'series' },
      };
    }),
  });
}

export function rollingRiskChart(
  el,
  {
    dates = [],
    portfolioVol = [],
    benchmarkVol = [],
    beta = [],
    mode = 'vol',
    labels = {},
  } = {},
) {
  if (!dates.length) return null;
  const accent = color('--accent', '#5ad1ff');
  const violet = color('--violet', '#8b93ff');
  const mute = C.mute;
  const ticks = sparseDates(dates, Math.min(8, Math.max(3, Math.floor(el.clientWidth / 80))));
  const betaMode = mode === 'beta' && beta.some(isNum);
  if (!betaMode && !portfolioVol.some(isNum)) return null;

  const series = betaMode
    ? [
        {
          name: labels.beta || '组合 Beta',
          type: 'line',
          data: beta,
          smooth: 0.12,
          symbol: 'none',
          connectNulls: false,
          lineStyle: { width: 1.7, color: violet },
          itemStyle: { color: violet },
          areaStyle: { color: areaGradient(violet, 0.09) },
          markLine: {
            silent: true,
            symbol: 'none',
            label: {
              show: true,
              position: 'insideEndTop',
              formatter: '1.0',
              color: mute,
              fontSize: 11,
              fontFamily: FONT,
            },
            lineStyle: { color: mute, type: 'dashed', opacity: 0.5 },
            data: [{ yAxis: 1 }],
          },
        },
      ]
    : [
        {
          name: labels.portfolio || '组合',
          type: 'line',
          data: portfolioVol,
          smooth: 0.12,
          symbol: 'none',
          connectNulls: false,
          lineStyle: { width: 1.8, color: accent },
          itemStyle: { color: accent },
          areaStyle: { color: areaGradient(accent, 0.12) },
        },
        {
          name: labels.benchmark || '基准',
          type: 'line',
          data: benchmarkVol,
          smooth: 0.12,
          symbol: 'none',
          connectNulls: false,
          lineStyle: { width: 1.2, color: mute, type: 'dashed' },
          itemStyle: { color: mute },
        },
      ];

  const keys = series
    .filter((item) => item.data.some(isNum))
    .map((item) => item.name);
  return create(el, {
    tooltip: tooltip({
      formatter: (params) => {
        const date = params?.[0]?.axisValueLabel || params?.[0]?.axisValue || '';
        const rows = params
          .map((item) => {
            const value = isNum(item.value)
              ? betaMode
                ? Number(item.value).toFixed(2)
                : `${Number(item.value).toFixed(1)}%`
              : '—';
            return `<div style="display:flex;justify-content:space-between;gap:22px"><span style="color:${item.color}">${esc(item.seriesName)}</span><span>${value}</span></div>`;
          })
          .join('');
        return `<div style="font-family:${FONT};font-size:12px;min-width:164px"><div style="color:${C.mute};margin-bottom:4px">${esc(date)} · ${betaMode ? '滚动 Beta' : '滚动波动率'}</div>${rows}</div>`;
      },
    }),
    legend: betaMode ? legend({ show: false }) : legend({ data: keys }),
    grid: { left: 8, right: 14, top: betaMode ? 14 : 32, bottom: 4, containLabel: true },
    xAxis: categoryAxis(dates, {
      axisLabel: { color: C.mute, fontSize: 11.5, fontFamily: FONT, ...ticks },
    }),
    yAxis: valueAxis({
      scale: true,
      axisLabel: {
        color: C.mute,
        fontSize: 11.5,
        fontFamily: FONT,
        formatter: (value) => (betaMode ? Number(value).toFixed(1) : `${Number(value).toFixed(0)}%`),
      },
    }),
    series,
  });
}

export function riskReturnScatter(el, metrics, { labels = {} } = {}) {
  const points = (metrics || []).filter(
    (item) => isNum(item.volatility) && isNum(item.annual_return) && item.symbol,
  );
  if (!points.length) return null;
  const colors = palette();
  return create(el, {
    tooltip: {
      ...tooltip({ trigger: 'item' }),
      formatter: (params) => {
        const item = params.data || {};
        const row = (name, value) =>
          `<div style="display:flex;justify-content:space-between;gap:20px"><span style="color:${C.mute}">${name}</span><span>${value}</span></div>`;
        return `<div style="font-family:${FONT};font-size:12px;line-height:1.75;min-width:150px">
          <div style="color:${C.text};font-weight:600;margin-bottom:3px">${esc(item.name)} · ${esc(labels[item.name] || '')}</div>
          ${row('年化收益', fmtPct(item.annual))}
          ${row('年化波动', fmtPct(item.vol, 2, false))}
          ${row('区间收益', fmtPct(item.total))}
          ${row('夏普比率', fmtNum(item.sharpe, 2))}
          ${row('最大回撤', fmtPct(item.drawdown))}
        </div>`;
      },
    },
    grid: { left: 14, right: 24, top: 38, bottom: 36, containLabel: true },
    xAxis: valueAxis({
      name: '年化波动率 %',
      nameLocation: 'middle',
      nameGap: 27,
      nameTextStyle: { color: C.mute, fontSize: 11.5, fontFamily: FONT },
      axisLabel: { color: C.mute, fontSize: 11.5, fontFamily: FONT, formatter: (value) => `${Number(value).toFixed(0)}%` },
    }),
    yAxis: valueAxis({
      name: '年化收益 %',
      nameTextStyle: { color: C.mute, fontSize: 11.5, padding: [0, 0, 6, 0] },
      axisLabel: { color: C.mute, fontSize: 11.5, fontFamily: FONT, formatter: (value) => `${Number(value).toFixed(0)}%` },
    }),
    series: [
      {
        type: 'scatter',
        symbolSize: 13,
        data: points.map((item, index) => ({
          name: item.symbol,
          value: [Number(item.volatility), Number(item.annual_return)],
          vol: Number(item.volatility),
          annual: Number(item.annual_return),
          total: item.total_return,
          sharpe: item.sharpe,
          drawdown: item.max_drawdown,
          itemStyle: { color: colors[index % colors.length], shadowBlur: 10, shadowColor: hexToRgba(colors[index % colors.length], 0.35) },
        })),
        label: {
          show: true,
          position: 'top',
          distance: 5,
          color: C.dim,
          fontSize: 12,
          fontFamily: FONT,
          formatter: (params) => params.data.name,
        },
        markLine: {
          silent: true,
          symbol: 'none',
          label: { color: C.mute, fontSize: 12, formatter: '零收益', position: 'insideEndTop' },
          lineStyle: { color: C.border, type: 'dashed' },
          data: [{ yAxis: 0 }],
        },
        emphasis: { scale: 1.5 },
      },
    ],
  });
}

export function correlationHeatmap(el, { symbols = [], matrix = [] }) {
  if (!symbols.length || !matrix.length) return null;
  const data = [];
  matrix.forEach((row, y) => {
    row.forEach((value, x) => {
      if (isNum(value)) data.push([x, y, Number(value)]);
    });
  });
  const compact = el.clientWidth < 560;
  const rotate = compact && symbols.length > 5 ? 38 : 0;
  const labelSize = compact || symbols.length > 8 ? 10.5 : 12;
  return create(el, {
    tooltip: {
      trigger: 'item',
      backgroundColor: color('--chart-tooltip-bg', 'rgba(8, 14, 24, 0.97)'),
      borderColor: color('--chart-tooltip-border', 'rgba(126, 160, 214, 0.26)'),
      borderWidth: 1,
      padding: [8, 11],
      textStyle: { color: C.text, fontSize: 12.5, fontFamily: FONT },
      extraCssText: `border-radius: 9px; box-shadow: ${color('--chart-tooltip-shadow', '0 16px 40px rgba(0,0,0,.45)')};`,
      formatter: (params) => {
        const [x, y, value] = params.value;
        return `<div style="font-family:${FONT};font-size:12px">${esc(symbols[y])} × ${esc(symbols[x])}<br/><span style="color:${C.mute}">相关系数</span> <b>${Number(value).toFixed(3)}</b></div>`;
      },
    },
    grid: { left: 8, right: 8, top: 8, bottom: rotate ? 24 : 8, containLabel: true },
    xAxis: {
      type: 'category',
      data: symbols,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        color: C.dim,
        fontSize: labelSize,
        fontFamily: FONT,
        interval: symbols.length > 10 ? 'auto' : 0,
        rotate,
        margin: rotate ? 8 : 4,
      },
      splitArea: { show: false },
    },
    yAxis: {
      type: 'category',
      data: symbols,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: C.dim, fontSize: labelSize, fontFamily: FONT },
      splitArea: { show: false },
    },
    visualMap: {
      min: -1,
      max: 1,
      show: false,
      inRange: {
        color: [
          color('--chart-heat-low', '#f65c6c'),
          color('--chart-heat-mid', '#24324a'),
          color('--chart-heat-high', '#5ad1ff'),
        ],
      },
    },
    series: [
      {
        type: 'heatmap',
        data,
        label: {
          show: true,
          color: color('--chart-heat-text', '#e9eefb'),
          fontSize: 12,
          fontFamily: FONT,
          formatter: (params) => Number(params.value[2]).toFixed(2),
        },
        itemStyle: { borderColor: color('--chart-gap', '#070d17'), borderWidth: 2, borderRadius: 3 },
        emphasis: { itemStyle: { borderColor: color('--accent', '#5ad1ff') } },
      },
    ],
  });
}

export function donut(el, items, { paletteOverride = null } = {}) {
  const list = (items || []).filter((item) => isNum(item.value) && Number(item.value) > 0);
  if (!list.length) return null;
  const colors = paletteOverride || palette();
  return create(el, {
    color: colors,
    tooltip: {
      trigger: 'item',
      confine: true,
      backgroundColor: color('--chart-tooltip-bg', 'rgba(8, 14, 24, 0.97)'),
      borderColor: color('--chart-tooltip-border', 'rgba(126, 160, 214, 0.26)'),
      borderWidth: 1,
      padding: [8, 11],
      textStyle: { color: C.text, fontSize: 12.5, fontFamily: FONT },
      extraCssText: `border-radius: 9px; box-shadow: ${color('--chart-tooltip-shadow', '0 16px 40px rgba(0,0,0,.45)')};`,
      formatter: (params) => {
        return `<div style="font-family:${FONT};font-size:12px;min-width:130px"><div style="color:${C.text};margin-bottom:3px">${esc(params.name)}</div><div style="display:flex;justify-content:space-between;gap:16px"><span style="color:${C.mute}">市值</span><span>${fmtCompact(params.value)}美元</span></div><div style="display:flex;justify-content:space-between;gap:16px"><span style="color:${C.mute}">占比</span><span>${Number(params.percent).toFixed(1)}%</span></div></div>`;
      },
    },
    series: [
      {
        type: 'pie',
        radius: ['65%', '88%'],
        center: ['50%', '50%'],
        avoidLabelOverlap: true,
        padAngle: 1.5,
        itemStyle: { borderColor: color('--chart-panel', '#0b1320'), borderWidth: 2, borderRadius: 3 },
        label: { show: false },
        labelLine: { show: false },
        emphasis: {
          scale: false,
          itemStyle: { shadowBlur: 0 },
        },
        data: list.map((item) => ({ name: item.name, value: Number(item.value) })),
      },
    ],
  });
}

export function breadthGauge(el, ratio) {
  const value = isNum(ratio) ? Number(ratio) : 0;
  const up = value >= 50 ? color('--up', '#34d399') : color('--down', '#f65c6c');
  return create(el, {
    animationDuration: 600,
    series: [
      {
        type: 'gauge',
        startAngle: 205,
        endAngle: -25,
        min: 0,
        max: 100,
        center: ['50%', '72%'],
        radius: '105%',
        progress: { show: true, width: 11, roundCap: true, itemStyle: { color: up } },
        axisLine: { lineStyle: { width: 11, color: [[1, C.border]] } },
        pointer: { show: false },
        axisTick: { show: false },
        splitLine: { show: false },
        axisLabel: { show: false },
        anchor: { show: false },
        title: { show: false },
        detail: {
          valueAnimation: true,
          formatter: (current) => `${Number(current).toFixed(1)}%`,
          offsetCenter: [0, '-18%'],
          color: C.text,
          fontSize: 26,
          fontFamily: FONT,
          fontWeight: 500,
        },
        data: [{ value }],
      },
    ],
  });
}

function macroDates(points, formatter) {
  const dates = (points || []).map((point) => point.d);
  if (!dates.length) return { dates, formatter };
  const firstYear = Number(String(dates[0]).slice(0, 4));
  const lastYear = Number(String(dates[dates.length - 1]).slice(0, 4));
  const span = lastYear - firstYear;
  const fallback = (value) => {
    const text = String(value);
    return span >= 3 ? text.slice(0, 7) : text.slice(5);
  };
  return { dates, formatter: formatter || fallback };
}

export function macroLine(el, points, { color: hex = null, unit = '', name = '', threshold = null, labelFormatter = null } = {}) {
  const clean = (points || []).filter((point) => isNum(point.v));
  if (!clean.length) return null;
  const lineColor = hex || color('--accent', '#5ad1ff');
  const { dates, formatter } = macroDates(clean, labelFormatter);
  const values = clean.map((point) => Number(point.v));
  return create(el, {
    tooltip: tooltip({
      formatter: (params) => {
        const index = params?.[0]?.dataIndex;
        const point = clean[index];
        if (!point) return '';
        return `<div style="font-family:${FONT};font-size:12px;line-height:1.7"><div style="color:${C.mute}">${point.d}</div><div style="display:flex;justify-content:space-between;gap:20px"><span>${name || '数值'}</span><span style="color:${lineColor}">${Number(point.v).toFixed(2)}${unit}</span></div></div>`;
      },
    }),
    grid: { left: 8, right: 14, top: 16, bottom: 6, containLabel: true },
    xAxis: categoryAxis(dates, {
      axisLabel: { color: C.mute, fontSize: 11.5, fontFamily: FONT, formatter, hideOverlap: true },
    }),
    yAxis: valueAxis({
      scale: true,
      axisLabel: { color: C.mute, fontSize: 11.5, fontFamily: FONT, formatter: (value) => `${value}${unit}` },
    }),
    series: [
      {
        type: 'line',
        name: name || '数值',
        data: values,
        smooth: 0.18,
        symbol: 'none',
        lineStyle: { width: 1.7, color: lineColor },
        areaStyle: { color: areaGradient(lineColor, 0.16) },
        markLine: threshold !== null
          ? {
              silent: true,
              symbol: 'none',
              label: { color: C.mute, fontSize: 11.5, formatter: `阈值 ${threshold}${unit}`, position: 'insideEndTop' },
              lineStyle: { color: hexToRgba(color('--down', '#f65c6c'), 0.55), type: 'dashed' },
              data: [{ yAxis: threshold }],
            }
          : undefined,
      },
    ],
  });
}

export function macroMultiLine(el, groups, { unit = '%', valueFormatter = null } = {}) {
  const list = (groups || []).filter((group) => Array.isArray(group.points) && group.points.length);
  if (!list.length) return null;
  const colors = palette();
  const formatter = (value) => {
    const text = String(value);
    return text.slice(0, 7);
  };
  return create(el, {
    tooltip: tooltip({
      formatter: (params) => {
        const date = params?.[0]?.axisValueLabel || '';
        const rows = params
          .filter((item) => isNum(item.value))
          .map(
            (item) =>
              `<div style="display:flex;justify-content:space-between;gap:20px"><span style="color:${item.color}">${esc(item.seriesName)}</span><span>${Number(item.value).toFixed(2)}${unit}</span></div>`,
          )
          .join('');
        return `<div style="font-family:${FONT};font-size:12px;min-width:160px"><div style="color:${C.mute};margin-bottom:3px">${esc(date)}</div>${rows}</div>`;
      },
    }),
    legend: legend({ data: list.map((group) => group.name) }),
    grid: { left: 8, right: 14, top: 30, bottom: 5, containLabel: true },
    xAxis: {
      type: 'time',
      axisLine: { lineStyle: { color: C.border } },
      axisTick: { show: false },
      axisLabel: {
        color: C.mute,
        fontSize: 11.5,
        fontFamily: FONT,
        hideOverlap: true,
        formatter: (value) => {
          const date = new Date(value);
          if (Number.isNaN(date.getTime())) return '';
          return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
        },
      },
      splitLine: { show: false },
    },
    yAxis: valueAxis({
      scale: true,
      axisLabel: {
        color: C.mute,
        fontSize: 11.5,
        fontFamily: FONT,
        formatter: valueFormatter || ((value) => `${value}${unit}`),
      },
    }),
    series: list.map((group, index) => {
      const lineColor = group.color || colors[index % colors.length];
      return {
        name: group.name,
        type: 'line',
        data: group.points.filter((point) => isNum(point.v)).map((point) => [point.d, Number(point.v)]),
        smooth: group.step ? false : 0.16,
        step: group.step ? 'end' : false,
        symbol: 'none',
        lineStyle: { width: 1.6, color: lineColor, type: group.dashed ? 'dashed' : 'solid' },
        itemStyle: { color: lineColor },
        emphasis: { focus: 'series' },
        areaStyle: group.area ? { color: areaGradient(lineColor, 0.14) } : undefined,
      };
    }),
  });
}

export function yieldCurve(el, current, previous) {
  const currentList = (current || []).filter((item) => isNum(item.value));
  if (!currentList.length) return null;
  const accent = color('--accent', '#5ad1ff');
  const muted = color('--text-mute', '#61718c');
  const terms = currentList.map((item) => item.term);
  const prevMap = new Map((previous || []).map((item) => [item.term, item.value]));
  return create(el, {
    tooltip: tooltip({
      formatter: (params) => {
        const rows = params
          .map(
            (item) =>
              `<div style="display:flex;justify-content:space-between;gap:20px"><span style="color:${item.color}">${item.seriesName}</span><span>${Number(item.value).toFixed(2)}%</span></div>`,
          )
          .join('');
        return `<div style="font-family:${FONT};font-size:12px;min-width:150px"><div style="color:${C.mute};margin-bottom:3px">${params?.[0]?.axisValue || ''} 期限</div>${rows}</div>`;
      },
    }),
    legend: legend({ data: ['当前曲线', '一年前'] }),
    grid: { left: 8, right: 18, top: 30, bottom: 6, containLabel: true },
    xAxis: categoryAxis(terms, { boundaryGap: false }),
    yAxis: valueAxis({
      scale: true,
      axisLabel: { color: C.mute, fontSize: 11.5, fontFamily: FONT, formatter: (value) => `${Number(value).toFixed(1)}%` },
    }),
    series: [
      {
        name: '当前曲线',
        type: 'line',
        data: currentList.map((item) => Number(item.value)),
        smooth: 0.2,
        symbol: 'circle',
        symbolSize: 5,
        lineStyle: { width: 2, color: accent },
        itemStyle: { color: accent },
        areaStyle: { color: areaGradient(accent, 0.13) },
      },
      {
        name: '一年前',
        type: 'line',
        data: terms.map((term) => (isNum(prevMap.get(term)) ? Number(prevMap.get(term)) : null)),
        smooth: 0.2,
        symbol: 'circle',
        symbolSize: 4,
        connectNulls: true,
        lineStyle: { width: 1.2, color: muted, type: 'dashed' },
        itemStyle: { color: muted },
      },
    ],
  });
}

export function barListChart(el, items, { tone = 'performance' } = {}) {
  const list = (items || []).filter((item) => isNum(item.value));
  if (!list.length) return null;
  const accent = color('--accent', '#5ad1ff');
  return create(el, {
    tooltip: tooltip({
      formatter: (params) => `${esc(params[0].name)}: ${Number(params[0].value).toFixed(2)}%`,
    }),
    grid: { left: 8, right: 16, top: 8, bottom: 2, containLabel: true },
    xAxis: valueAxis({ axisLabel: { show: false }, splitLine: { show: false } }),
    yAxis: categoryAxis(list.map((item) => item.name), {
      inverse: true,
      boundaryGap: true,
      axisLabel: { color: C.dim, fontSize: 12, fontFamily: FONT },
      axisLine: { show: false },
    }),
    series: [
      {
        type: 'bar',
        data: list.map((item) => {
          const value = Number(item.value);
          const hex = tone === 'allocation' ? accent : value >= 0 ? color('--up') : color('--down');
          return {
            value,
            itemStyle: {
              color: horizontalBarGradient(hex, { negative: tone !== 'allocation' && value < 0 }),
              borderRadius: 3,
            },
          };
        }),
        barWidth: 7,
        itemStyle: { borderRadius: 3 },
        markLine: { silent: true, symbol: 'none', label: { show: false }, lineStyle: { color: accent, opacity: 0.25 }, data: [{ xAxis: 0 }] },
      },
    ],
  });
}

export function macroQuadrant(el, { trail = [], current = null, thresholds = {} } = {}) {
  const points = (trail || []).filter((item) => isNum(item.x) && isNum(item.y));
  if (!points.length && !current) return null;
  const all = current ? [...points, current] : points;
  const growth = Number(thresholds.growth ?? 0);
  const inflation = Number(thresholds.inflation ?? 2);
  const xs = all.map((item) => Number(item.x));
  const ys = all.map((item) => Number(item.y));
  const xPad = Math.max(0.35, (Math.max(...xs) - Math.min(...xs)) * 0.18);
  const yPad = Math.max(0.25, (Math.max(...ys) - Math.min(...ys)) * 0.18);
  const minX = Math.min(growth, ...xs) - xPad;
  const maxX = Math.max(growth, ...xs) + xPad;
  const minY = Math.max(0, Math.min(inflation, ...ys) - yPad);
  const maxY = Math.max(inflation, ...ys) + yPad;
  const accent = color('--accent', '#5ad1ff');
  const up = color('--up', '#34d399');
  const down = color('--down', '#f65c6c');
  const gold = color('--gold', '#f0b35a');
  const violet = color('--violet', '#8b93ff');
  const quadrantStyle = (hex) => ({ color: hexToRgba(hex, 0.055) });
  const areaLabel = { show: true, position: 'insideTopLeft', fontSize: 11, fontFamily: FONT, color: C.mute, distance: 8 };
  return create(el, {
    animation: false,
    tooltip: tooltip({
      formatter: (params) => {
        const item = (params || []).find((entry) => entry.seriesType === 'scatter' || entry.seriesType === 'line');
        const value = item?.value;
        if (!Array.isArray(value) || value.length < 2) return '';
        return `<div style="font-family:${FONT};font-size:12px;line-height:1.7"><div style="color:${C.mute};margin-bottom:2px">${esc(value[2] || '')}</div><div>增长动能 <b>${Number(value[0]).toFixed(2)}</b></div><div>核心通胀 <b>${Number(value[1]).toFixed(2)}%</b></div></div>`;
      },
    }),
    grid: { left: 10, right: 18, top: 18, bottom: 14, containLabel: true },
    xAxis: valueAxis({
      name: '增长动能 · CFNAI 3M',
      nameLocation: 'middle',
      nameGap: 28,
      min: minX,
      max: maxX,
      axisLabel: { color: C.mute, fontSize: 11.5, fontFamily: FONT, formatter: (value) => Number(value).toFixed(1) },
    }),
    yAxis: valueAxis({
      name: '核心通胀 · %',
      nameLocation: 'middle',
      nameGap: 42,
      min: minY,
      max: maxY,
      axisLabel: { color: C.mute, fontSize: 11.5, fontFamily: FONT, formatter: (value) => Number(value).toFixed(1) },
    }),
    series: [
      {
        type: 'line',
        data: points.map((item) => [Number(item.x), Number(item.y), item.date]),
        symbol: 'circle',
        symbolSize: 3,
        silent: true,
        lineStyle: { width: 1, color: accent, opacity: 0.32 },
        itemStyle: { color: accent, opacity: 0.35 },
        markLine: {
          silent: true,
          symbol: 'none',
          label: { show: false },
          lineStyle: { color: C.mute, type: 'dashed', opacity: 0.38 },
          data: [{ xAxis: growth }, { yAxis: inflation }],
        },
        markArea: {
          silent: true,
          data: [
            [{ name: '滞胀', coord: [minX, inflation], itemStyle: quadrantStyle(down), label: areaLabel }, { coord: [growth, maxY] }],
            [{ name: '再通胀', coord: [growth, inflation], itemStyle: quadrantStyle(gold), label: areaLabel }, { coord: [maxX, maxY] }],
            [{ name: '放缓', coord: [minX, minY], itemStyle: quadrantStyle(violet), label: areaLabel }, { coord: [growth, inflation] }],
            [{ name: '复苏', coord: [growth, minY], itemStyle: quadrantStyle(up), label: areaLabel }, { coord: [maxX, inflation] }],
          ],
        },
      },
      current
        ? {
            type: 'scatter',
            data: [{ value: [Number(current.x), Number(current.y), current.date] }],
            symbolSize: 10,
            itemStyle: { color: accent, borderColor: color('--panel', '#fff'), borderWidth: 2 },
            z: 5,
          }
        : { type: 'scatter', data: [] },
    ],
  });
}

export function annualReturnsChart(el, rows = []) {
  const clean = (rows || []).filter((item) => item && item.year && isNum(item.portfolio));
  if (!clean.length) return null;
  const up = color('--up', '#34d399');
  const down = color('--down', '#f65c6c');
  const benchmarkColor = color('--gold', '#f0b35a');
  const hasBenchmark = clean.some((item) => isNum(item.benchmark));
  return create(el, {
    tooltip: tooltip({
      formatter: (params) => {
        const index = params?.[0]?.dataIndex;
        const row = clean[index];
        if (!row) return '';
        const toneColor = Number(row.portfolio) >= 0 ? up : down;
        return `<div style="font-family:${FONT};font-size:12px;min-width:140px"><div style="color:${C.mute};margin-bottom:3px">${esc(String(row.year))} 年</div><div style="display:flex;justify-content:space-between;gap:18px"><span>组合</span><span style="color:${toneColor}">${Number(row.portfolio).toFixed(2)}%</span></div>${isNum(row.benchmark) ? `<div style="display:flex;justify-content:space-between;gap:18px"><span style="color:${C.mute}">基准</span><span>${Number(row.benchmark).toFixed(2)}%</span></div>` : ''}</div>`;
      },
    }),
    legend: legend({ data: ['组合', ...(hasBenchmark ? ['基准'] : [])] }),
    grid: { left: 8, right: 14, top: 30, bottom: 6, containLabel: true },
    xAxis: categoryAxis(clean.map((item) => String(item.year)), { boundaryGap: true }),
    yAxis: valueAxis({ axisLabel: { color: C.mute, fontSize: 11.5, fontFamily: FONT, formatter: (value) => `${Number(value).toFixed(0)}%` } }),
    series: [
      {
        name: '组合',
        type: 'bar',
        data: clean.map((item) => {
          const value = Number(item.portfolio);
          const hex = value >= 0 ? up : down;
          return {
            value,
            itemStyle: {
              color: {
                type: 'linear',
                x: 0,
                y: 0,
                x2: 0,
                y2: 1,
                colorStops: value >= 0
                  ? [
                      { offset: 0, color: hexToRgba(hex, 0.74) },
                      { offset: 1, color: hexToRgba(hex, 0.3) },
                    ]
                  : [
                      { offset: 0, color: hexToRgba(hex, 0.3) },
                      { offset: 1, color: hexToRgba(hex, 0.74) },
                    ],
              },
              borderRadius: [3, 3, 0, 0],
            },
          };
        }),
        barMaxWidth: 24,
      },
      hasBenchmark
        ? {
            name: '基准',
            type: 'line',
            data: clean.map((item) => (isNum(item.benchmark) ? Number(item.benchmark) : null)),
            symbol: 'circle',
            symbolSize: 4,
            connectNulls: false,
            lineStyle: { width: 1.2, color: benchmarkColor, type: 'dashed' },
            itemStyle: { color: benchmarkColor },
          }
        : { type: 'line', data: [] },
    ],
  });
}
