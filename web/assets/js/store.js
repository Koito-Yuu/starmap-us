import { sanitizeIndicatorParams } from './technical.js';

const SETTINGS_KEY = 'starmap.settings.v1';
const WATCHLIST_KEY = 'starmap.watchlist.v1';
const PORTFOLIO_DRAFT_KEY = 'starmap.portfolio-draft.v1';
const PORTFOLIOS_KEY = 'starmap.portfolios.v1';

const DEFAULT_WATCHLIST = ['AAPL', 'MSFT', 'NVDA', 'AMZN', 'META'];
const PORTFOLIO_RANGES = ['1Y', '3Y', '5Y'];
const PORTFOLIO_BENCHMARKS = ['SPY', 'QQQ', 'IWM', 'DIA'];
const REBALANCE_MODES = ['buy_hold', 'monthly', 'quarterly', 'annual'];

function readJSON(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw);
    return parsed ?? fallback;
  } catch {
    return fallback;
  }
}

function writeJSON(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage may be unavailable in private mode */
  }
}

function emit(type) {
  window.dispatchEvent(new CustomEvent('starmap:store', { detail: { type } }));
}

function normalizeHoldings(list) {
  if (!Array.isArray(list)) return [];
  const seen = new Set();
  return list
    .filter((item) => item && typeof item === 'object')
    .map((item) => ({
      symbol: String(item.symbol || '').trim().toUpperCase(),
      weight: Number(item.weight),
    }))
    .filter((item) => {
      if (!item.symbol || !Number.isFinite(item.weight) || item.weight <= 0 || seen.has(item.symbol)) return false;
      seen.add(item.symbol);
      return true;
    })
    .slice(0, 20);
}

function normalizePortfolio(value) {
  const source = value && typeof value === 'object' ? value : {};
  return {
    id: String(source.id || ''),
    name: String(source.name || '').trim().slice(0, 60),
    holdings: normalizeHoldings(source.holdings),
    range: PORTFOLIO_RANGES.includes(source.range) ? source.range : '1Y',
    benchmark: PORTFOLIO_BENCHMARKS.includes(source.benchmark) ? source.benchmark : 'SPY',
    rebalance: REBALANCE_MODES.includes(source.rebalance) ? source.rebalance : 'quarterly',
    updatedAt: String(source.updatedAt || ''),
  };
}

function portfolioId() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID();
  return `pf-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

export const store = {
  settings() {
    const value = readJSON(SETTINGS_KEY, {});
    return {
      scheme: value.scheme === 'cn' ? 'cn' : 'us',
      theme: value.theme === 'dark' ? 'dark' : 'light',
      chart: value.chart && typeof value.chart === 'object' ? value.chart : {},
      sidebar: value.sidebar && typeof value.sidebar === 'object' ? value.sidebar : {},
      fundSymbols: Array.isArray(value.fundSymbols) ? value.fundSymbols : [],
    };
  },

  sidebar() {
    const value = this.settings().sidebar || {};
    return {
      collapsed: value.collapsed === true,
      watchOpen: value.watchOpen !== false,
    };
  },

  setSidebarPref(key, value) {
    const settings = this.settings();
    writeJSON(SETTINGS_KEY, {
      ...settings,
      sidebar: { ...settings.sidebar, [key]: Boolean(value) },
    });
  },

  chartPrefs() {
    const chart = this.settings().chart;
    return {
      ma: chart.ma !== false,
      macd: chart.macd !== false,
      rsi: chart.rsi === true,
      log: chart.log === true,
      levels: chart.levels !== false,
      channel: ['none', 'bb', 'kc', 'donchian', 'regression', 'vwap', 'adaptive'].includes(chart.channel) ? chart.channel : 'bb',
      trend: ['none', 'supertrend', 'kama'].includes(chart.trend) ? chart.trend : 'none',
      study: ['none', 'adx', 'stochastic', 'cmf', 'obv', 'atr', 'squeeze'].includes(chart.study) ? chart.study : 'none',
    };
  },

  setChartPref(key, value) {
    const chart = this.chartPrefs();
    if (!(key in chart)) return;
    writeJSON(SETTINGS_KEY, {
      ...this.settings(),
      chart: {
        ...this.settings().chart,
        ...chart,
        [key]: typeof chart[key] === 'boolean' ? Boolean(value) : String(value),
      },
    });
  },

  chartParams() {
    return sanitizeIndicatorParams(this.settings().chart.parameters);
  },

  setChartParams(params) {
    writeJSON(SETTINGS_KEY, {
      ...this.settings(),
      chart: { ...this.settings().chart, parameters: sanitizeIndicatorParams(params) },
    });
  },

  scheme() {
    return this.settings().scheme;
  },

  setScheme(scheme) {
    const next = scheme === 'cn' ? 'cn' : 'us';
    writeJSON(SETTINGS_KEY, { ...this.settings(), scheme: next });
    emit('scheme');
    return next;
  },

  toggleScheme() {
    return this.setScheme(this.scheme() === 'us' ? 'cn' : 'us');
  },

  theme() {
    return this.settings().theme;
  },

  setTheme(theme) {
    const next = theme === 'dark' ? 'dark' : 'light';
    writeJSON(SETTINGS_KEY, { ...this.settings(), theme: next });
    emit('theme');
    return next;
  },

  toggleTheme() {
    return this.setTheme(this.theme() === 'dark' ? 'light' : 'dark');
  },

  rememberFund(symbol) {
    const settings = this.settings();
    const code = String(symbol).toUpperCase();
    if (!settings.fundSymbols.includes(code)) {
      writeJSON(SETTINGS_KEY, { ...settings, fundSymbols: [...settings.fundSymbols, code] });
    }
  },

  symbolPath(symbol) {
    const code = String(symbol).toUpperCase();
    return `#/${this.settings().fundSymbols.includes(code) ? 'fund' : 'stock'}/${encodeURIComponent(code)}`;
  },

  watchlist() {
    const value = readJSON(WATCHLIST_KEY, null);
    if (!Array.isArray(value)) return [...DEFAULT_WATCHLIST];
    return Array.from(new Set(value.map((item) => String(item || '').toUpperCase()).filter(Boolean)));
  },

  setWatchlist(list) {
    const clean = Array.from(new Set((list || []).map((item) => String(item || '').toUpperCase()).filter(Boolean)));
    writeJSON(WATCHLIST_KEY, clean);
    emit('watchlist');
    return clean;
  },

  isWatched(symbol) {
    return this.watchlist().includes(String(symbol || '').toUpperCase());
  },

  addWatch(symbol) {
    const code = String(symbol || '').toUpperCase();
    if (!code) return false;
    const list = this.watchlist();
    if (list.includes(code)) return false;
    list.push(code);
    this.setWatchlist(list);
    return true;
  },

  removeWatch(symbol) {
    const code = String(symbol || '').toUpperCase();
    const list = this.watchlist().filter((item) => item !== code);
    this.setWatchlist(list);
    return list;
  },

  toggleWatch(symbol) {
    return this.isWatched(symbol) ? (this.removeWatch(symbol), false) : (this.addWatch(symbol), true);
  },

  portfolioDraft() {
    return normalizePortfolio(readJSON(PORTFOLIO_DRAFT_KEY, {}));
  },

  setPortfolioDraft(value) {
    const draft = normalizePortfolio(value);
    writeJSON(PORTFOLIO_DRAFT_KEY, draft);
    return draft;
  },

  savedPortfolios() {
    const value = readJSON(PORTFOLIOS_KEY, []);
    if (!Array.isArray(value)) return [];
    return value
      .map((item) => normalizePortfolio(item))
      .filter((item) => item.id && item.name && item.holdings.length);
  },

  savePortfolio(value) {
    const entry = normalizePortfolio({
      ...value,
      id: value?.id || portfolioId(),
      updatedAt: new Date().toISOString(),
    });
    const list = this.savedPortfolios();
    const index = list.findIndex((item) => item.id === entry.id);
    if (index >= 0) list[index] = entry;
    else list.unshift(entry);
    writeJSON(PORTFOLIOS_KEY, list);
    emit('portfolios');
    return entry;
  },

  deletePortfolio(id) {
    const list = this.savedPortfolios().filter((item) => item.id !== id);
    writeJSON(PORTFOLIOS_KEY, list);
    emit('portfolios');
    return list;
  },

  sampleHoldings() {
    return [
      { symbol: 'AAPL', weight: 18 },
      { symbol: 'MSFT', weight: 18 },
      { symbol: 'NVDA', weight: 18 },
      { symbol: 'AMZN', weight: 14 },
      { symbol: 'GOOGL', weight: 12 },
      { symbol: 'META', weight: 10 },
      { symbol: 'JPM', weight: 10 },
    ];
  },
};
