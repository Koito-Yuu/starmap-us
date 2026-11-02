import { api } from './api.js';
import { store } from './store.js';
import * as ui from './ui.js';
import * as charts from './charts.js';
import { debounce, fmtDate, fmtPct, fmtPrice, nowET, todayCn } from './utils.js';
import * as overview from './views/overview.js';
import * as stock from './views/stock.js';
import * as screener from './views/screener.js';
import * as watchlist from './views/watchlist.js';
import * as compare from './views/compare.js';
import * as portfolio from './views/portfolio.js';
import * as macro from './views/macro.js';
import * as fund from './views/fund.js';

const routes = { overview, stock, screener, watchlist, compare, portfolio, macro, fund };
const root = document.getElementById('view-root');
const pageTitle = document.getElementById('page-title');
const pageEyebrow = document.getElementById('page-eyebrow');
const navLinks = Array.from(document.querySelectorAll('.nav-link'));

let currentCleanup = null;
let currentAbort = null;
let renderToken = 0;

function applyScheme(scheme) {
  document.documentElement.dataset.scheme = scheme;
  const label = document.getElementById('scheme-label');
  if (label) label.textContent = scheme === 'cn' ? '中式' : '美式';
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const label = document.getElementById('theme-label');
  if (label) label.textContent = theme === 'dark' ? '暗色' : '亮色';
  const button = document.getElementById('theme-toggle');
  if (button) {
    button.setAttribute('aria-pressed', String(theme === 'dark'));
    button.title = theme === 'dark' ? '切换为亮色模式' : '切换为暗色模式';
  }
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', theme === 'dark' ? '#0d1118' : '#f5f6f8');
}

function parseRoute() {
  const raw = location.hash.replace(/^#\/?/, '');
  const [pathPart, queryPart] = raw.split('?');
  const parts = pathPart.split('/').filter(Boolean);
  const query = new URLSearchParams(queryPart || '');
  const queryParams = Object.fromEntries(query.entries());
  if (parts[0] === 'stock' && parts[1]) {
    return {
      name: 'stock',
      params: { ...queryParams, query, symbol: decodeURIComponent(parts[1]).toUpperCase() },
    };
  }
  if (parts[0] === 'fund') {
    return {
      name: 'fund',
      params: { ...queryParams, query, ticker: parts[1] ? decodeURIComponent(parts[1]).toUpperCase() : '' },
    };
  }
  if (parts[0] && routes[parts[0]]) return { name: parts[0], params: { ...queryParams, query } };
  return { name: 'overview', params: { ...queryParams, query } };
}

function go(symbolOrHash) {
  const target = String(symbolOrHash || '').startsWith('#') ? symbolOrHash : store.symbolPath(symbolOrHash);
  if (location.hash === target) {
    renderRoute();
    return;
  }
  location.hash = target;
}

function genericSkeleton() {
  return `
    <section class="view">
      <div class="skeleton">
        <div class="sk sk-line w25" style="height:10px"></div>
        <div class="sk sk-line w40" style="height:26px"></div>
        <div class="sk-grid sk-4" style="margin-top:14px">
          <div class="sk sk-card"></div><div class="sk sk-card"></div><div class="sk sk-card"></div><div class="sk sk-card"></div>
        </div>
        <div class="sk-grid sk-2">
          <div class="sk sk-panel"></div><div class="sk sk-panel"></div>
        </div>
      </div>
    </section>`;
}

async function renderRoute() {
  const token = ++renderToken;
  if (currentCleanup) {
    try {
      currentCleanup();
    } catch (error) {
      console.error(error);
    }
    currentCleanup = null;
  }
  if (currentAbort) currentAbort.abort();
  charts.disposeAll();

  const route = parseRoute();
  const view = routes[route.name];
  const controller = new AbortController();
  currentAbort = controller;

  const meta = view.meta || {};
  const symbol = route.name === 'stock' ? route.params.symbol : route.name === 'fund' ? route.params.ticker : '';
  const title = symbol || meta.title || '星图';
  pageTitle.textContent = symbol ? `${symbol} · ${meta.title || ''}`.trim() : meta.title || '星图';
  pageEyebrow.textContent = meta.eyebrow || 'STARMAP TERMINAL';
  document.title = `${title} · 星图 STARMAP`;
  navLinks.forEach((link) => link.classList.toggle('active', link.dataset.nav === route.name));

  const viewRoot = document.createElement('div');
  viewRoot.innerHTML = genericSkeleton();
  root.replaceChildren(viewRoot);
  window.scrollTo({ top: 0, behavior: 'auto' });

  try {
    const cleanup = await view.mount(viewRoot, route.params, {
      signal: controller.signal,
      isActive: () => token === renderToken,
      reload: () => renderRoute(),
      navigate: go,
    });
    if (token === renderToken) {
      currentCleanup = typeof cleanup === 'function' ? cleanup : null;
    } else if (typeof cleanup === 'function') {
      cleanup();
    }
  } catch (error) {
    if (error?.name === 'AbortError' || token !== renderToken) return;
    console.error(error);
    viewRoot.innerHTML = `<section class="view"><div class="panel">${ui.errorPanel(error?.message || '页面渲染失败')}</div></section>`;
    ui.bindRetry(viewRoot, renderRoute);
  }
}

function setupSearch() {
  const input = document.getElementById('global-search');
  const results = document.getElementById('search-results');
  const wrap = document.getElementById('search-wrap');
  if (!input || !results) return;
  let items = [];
  let activeIndex = -1;
  let requestController = null;

  const close = () => {
    results.hidden = true;
    results.innerHTML = '';
    activeIndex = -1;
  };

  const select = (symbol) => {
    if (!symbol) return;
    input.value = '';
    close();
    input.blur();
    go(symbol);
  };

  const paint = () => {
    if (!items.length) {
      results.innerHTML = `<div class="search-empty">未找到匹配的美股标的</div>`;
      results.hidden = false;
      return;
    }
    results.innerHTML = items
      .map(
        (item, index) => `
          <div class="search-item ${index === activeIndex ? 'active' : ''}" data-symbol="${ui.esc(item.symbol)}" data-index="${index}">
            <span class="s-symbol">${ui.esc(item.symbol)}</span>
            <span class="s-name">${ui.esc(item.name || '—')}</span>
            <span class="s-exchange">${ui.esc(item.exchange || 'US')}</span>
          </div>`,
      )
      .join('');
    results.hidden = false;
  };

  const search = debounce(async (value) => {
    if (requestController) requestController.abort();
    if (!value.trim()) {
      close();
      return;
    }
    requestController = new AbortController();
    results.innerHTML = `<div class="search-empty">搜索中…</div>`;
    results.hidden = false;
    try {
      const payload = await api.get(`/api/search?q=${encodeURIComponent(value.trim())}&limit=8`, {
        signal: requestController.signal,
        timeout: 20000,
      });
      items = payload.items || [];
      activeIndex = items.length ? 0 : -1;
      paint();
    } catch (error) {
      if (error?.name === 'AbortError') return;
      results.innerHTML = `<div class="search-empty">${ui.esc(error.message || '搜索失败')}</div>`;
      results.hidden = false;
    }
  }, 220);

  input.addEventListener('input', () => search(input.value));
  input.addEventListener('focus', () => {
    if (input.value.trim() && items.length) paint();
  });

  input.addEventListener('keydown', (event) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      if (!items.length) return;
      activeIndex = event.key === 'ArrowDown'
        ? (activeIndex + 1) % items.length
        : (activeIndex - 1 + items.length) % items.length;
      paint();
    } else if (event.key === 'Enter') {
      event.preventDefault();
      if (activeIndex >= 0 && items[activeIndex]) select(items[activeIndex].symbol);
      else if (items.length === 1) select(items[0].symbol);
      else if (input.value.trim()) select(input.value.trim().toUpperCase());
    } else if (event.key === 'Escape') {
      close();
      input.blur();
    }
  });

  results.addEventListener('click', (event) => {
    const target = event.target.closest('.search-item');
    if (target) select(target.dataset.symbol);
  });

  document.addEventListener('pointerdown', (event) => {
    if (!wrap.contains(event.target)) close();
  });

  document.addEventListener('keydown', (event) => {
    const tag = (event.target?.tagName || '').toLowerCase();
    const typing = ['input', 'textarea', 'select'].includes(tag) || event.target?.isContentEditable;
    if ((event.key === '/' && !typing) || ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k')) {
      event.preventDefault();
      input.focus();
      input.select();
    }
  });
}

function setupClock() {
  const clock = document.getElementById('market-clock');
  const timeEl = document.getElementById('clock-time');
  const stateEl = document.getElementById('clock-state');
  if (!clock || !timeEl || !stateEl) return;

  const tick = () => {
    timeEl.textContent = nowET();
  };
  tick();
  setInterval(tick, 1000);

  const sync = async () => {
    try {
      const status = await api.get('/api/market/status', { timeout: 10000 });
      clock.classList.toggle('is-open', status.state === 'open');
      clock.classList.toggle('is-closed', status.state !== 'open');
      stateEl.textContent = status.state === 'open' ? '盘中' : status.label || '休市';
      if (status.et_date) {
        clock.title = `美东 ${status.et_date} · ${status.label || ''}${status.next_open ? ` · 下次开盘 ${fmtDate(status.next_open, 'full')}` : ''}`;
      }
    } catch {
      clock.classList.remove('is-open');
      clock.classList.add('is-closed');
      stateEl.textContent = '离线';
    }
  };
  sync();
  setInterval(() => {
    if (!document.hidden) sync();
  }, 60000);
}

function setupSidebar() {
  const panel = document.getElementById('watch-panel');
  const list = document.getElementById('watch-list');
  const empty = document.getElementById('watch-empty');
  const countEl = document.getElementById('watch-count');
  const form = document.getElementById('watch-add');
  const input = document.getElementById('watch-input');
  const addBtn = document.getElementById('watch-add-btn');
  const compareBtn = document.getElementById('watch-compare');
  const watchToggle = document.getElementById('watch-toggle');
  const collapseBtn = document.getElementById('sidebar-collapse');
  if (!panel || !list) return;

  const quotes = new Map();
  let controller = null;
  let dragSymbol = '';
  const prefs = store.sidebar();

  const applyCollapsed = (collapsed, { animate = true } = {}) => {
    document.documentElement.dataset.sidebar = collapsed ? 'collapsed' : 'expanded';
    collapseBtn?.setAttribute('aria-expanded', String(!collapsed));
    if (collapseBtn) collapseBtn.title = collapsed ? '展开侧栏' : '收起侧栏';
    if (animate) setTimeout(() => charts.resizeAll(), 280);
  };

  const applyWatchOpen = (open) => {
    panel.classList.toggle('collapsed', !open);
    watchToggle?.setAttribute('aria-expanded', String(open));
  };

  applyCollapsed(prefs.collapsed, { animate: false });
  applyWatchOpen(prefs.watchOpen);

  const activeSymbol = () => {
    const route = parseRoute();
    return route.name === 'stock' ? route.params.symbol : route.name === 'fund' ? route.params.ticker : '';
  };

  const syncActive = () => {
    const symbol = activeSymbol();
    list.querySelectorAll('.watch-row').forEach((row) => {
      row.classList.toggle('active', row.dataset.symbol === symbol);
    });
  };

  const paint = () => {
    const symbols = store.watchlist();
    if (countEl) countEl.textContent = String(symbols.length);
    if (empty) empty.hidden = symbols.length > 0;
    if (compareBtn) compareBtn.disabled = symbols.length < 2;
    list.innerHTML = symbols
      .map((symbol) => {
        const quote = quotes.get(symbol);
        const change = quote?.change_pct;
        const hasChange = change !== null && change !== undefined && Number.isFinite(Number(change));
        const tone = hasChange ? (Number(change) > 0 ? 'pos' : Number(change) < 0 ? 'neg' : 'flat') : 'flat';
        const name = quote?.name && quote.name !== symbol ? quote.name : '';
        return `<div class="watch-row" data-symbol="${ui.esc(symbol)}" role="listitem" tabindex="0" draggable="true" title="${ui.esc(symbol)}${name ? ` · ${ui.esc(name)}` : ''}">
          <span class="watch-id">
            <span class="watch-symbol">${ui.esc(symbol)}</span>
            <span class="watch-name">${ui.esc(name || (store.settings().fundSymbols.includes(symbol) ? '基金档案' : '暂无行情'))}</span>
          </span>
          <span class="watch-quote">
            <span class="watch-price">${quote ? fmtPrice(quote.price) : '—'}</span>
            <span class="watch-chg ${tone}">${quote ? fmtPct(change) : '—'}</span>
          </span>
          <button class="watch-remove" type="button" data-remove="${ui.esc(symbol)}" title="移除自选" aria-label="移除 ${ui.esc(symbol)}">${ui.icon('x', 9)}</button>
        </div>`;
      })
      .join('');
    syncActive();
  };

  const load = async () => {
    const symbols = store.watchlist();
    if (!symbols.length) {
      paint();
      return;
    }
    controller?.abort();
    controller = new AbortController();
    try {
      const payload = await api.get(
        `/api/quotes?symbols=${encodeURIComponent(symbols.slice(0, 15).join(','))}`,
        { signal: controller.signal, timeout: 25000 },
      );
      let changed = false;
      (payload.items || []).forEach((item) => {
        if (!item?.symbol) return;
        quotes.set(item.symbol, item);
        changed = true;
      });
      if (changed) paint();
    } catch (error) {
      if (error?.name === 'AbortError') return;
      if (!list.querySelector('.watch-row')) {
        list.innerHTML = '<div class="watch-error">行情暂不可用，稍后自动重试</div>';
      }
    }
  };

  const openAdd = (open) => {
    if (!form) return;
    form.hidden = !open;
    addBtn?.classList.toggle('active', open);
    if (open) {
      input.value = '';
      input.focus();
    }
  };

  addBtn?.addEventListener('click', () => openAdd(form.hidden));
  form?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const code = String(input?.value || '').trim().toUpperCase();
    if (!/^[A-Z][A-Z0-9.\-]{0,9}$/.test(code)) {
      ui.toast('请输入有效的美股代码', 'warn');
      return;
    }
    if (store.isWatched(code)) {
      ui.toast(`${code} 已在自选中`, 'info');
      input.select();
      return;
    }
    if (store.watchlist().length >= 15) {
      ui.toast('自选最多 15 只，请先移除部分标的', 'warn');
      return;
    }
    const submit = form.querySelector('button[type="submit"]');
    if (submit) submit.disabled = true;
    try {
      const payload = await api.get(`/api/quotes?symbols=${encodeURIComponent(code)}`, {
        timeout: 20000,
      });
      const item = (payload.items || []).find((row) => row.symbol === code) || (payload.items || [])[0];
      if (!item) throw new Error(`未找到代码 ${code} 的行情`);
      quotes.set(item.symbol, item);
      store.addWatch(item.symbol);
      ui.toast(`已添加 ${item.symbol} 到自选`, 'success', 1800);
      openAdd(false);
    } catch (error) {
      ui.toast(error?.message || '添加自选失败', 'error');
    } finally {
      if (submit) submit.disabled = false;
    }
  });
  input?.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') openAdd(false);
  });

  list.addEventListener('click', (event) => {
    const remove = event.target.closest('[data-remove]');
    if (remove) {
      event.stopPropagation();
      const symbol = remove.dataset.remove;
      store.removeWatch(symbol);
      ui.toast(`已从自选移除 ${symbol}`, 'info', 1600);
      return;
    }
    const row = event.target.closest('.watch-row');
    if (row?.dataset.symbol) go(row.dataset.symbol);
  });

  list.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    const row = event.target.closest('.watch-row');
    if (!row || event.target !== row) return;
    event.preventDefault();
    go(row.dataset.symbol);
  });

  list.addEventListener('dragstart', (event) => {
    const row = event.target.closest('.watch-row');
    if (!row) return;
    dragSymbol = row.dataset.symbol;
    row.classList.add('dragging');
    event.dataTransfer.effectAllowed = 'move';
    try {
      event.dataTransfer.setData('text/plain', dragSymbol);
    } catch {
      /* older browsers may restrict the data store */
    }
  });

  const clearDrag = () => {
    dragSymbol = '';
    list.querySelectorAll('.watch-row').forEach((row) => row.classList.remove('dragging', 'drop-target'));
  };
  list.addEventListener('dragend', clearDrag);
  list.addEventListener('dragover', (event) => {
    if (!dragSymbol) return;
    event.preventDefault();
    const row = event.target.closest('.watch-row');
    list.querySelectorAll('.watch-row').forEach((item) => {
      item.classList.toggle('drop-target', item === row && item.dataset.symbol !== dragSymbol);
    });
  });
  list.addEventListener('dragleave', (event) => {
    if (!list.contains(event.relatedTarget)) {
      list.querySelectorAll('.drop-target').forEach((row) => row.classList.remove('drop-target'));
    }
  });
  list.addEventListener('drop', (event) => {
    if (!dragSymbol) return;
    event.preventDefault();
    const row = event.target.closest('.watch-row');
    if (!row || row.dataset.symbol === dragSymbol) {
      clearDrag();
      return;
    }
    const symbols = store.watchlist();
    const from = symbols.indexOf(dragSymbol);
    const to = symbols.indexOf(row.dataset.symbol);
    if (from >= 0 && to >= 0) {
      symbols.splice(from, 1);
      symbols.splice(to, 0, dragSymbol);
      store.setWatchlist(symbols);
    }
    clearDrag();
  });

  compareBtn?.addEventListener('click', () => {
    const symbols = store.watchlist().slice(0, 6);
    if (symbols.length < 2) {
      ui.toast('至少添加 2 只自选才能对比', 'warn');
      return;
    }
    go(`#/compare?symbols=${encodeURIComponent(symbols.join(','))}`);
  });

  watchToggle?.addEventListener('click', () => {
    const open = panel.classList.contains('collapsed');
    applyWatchOpen(open);
    store.setSidebarPref('watchOpen', open);
  });

  collapseBtn?.addEventListener('click', () => {
    const collapsed = document.documentElement.dataset.sidebar !== 'collapsed';
    applyCollapsed(collapsed);
    store.setSidebarPref('collapsed', collapsed);
  });

  window.addEventListener('starmap:store', (event) => {
    if (event.detail?.type !== 'watchlist') return;
    paint();
    load();
  });

  window.addEventListener('hashchange', syncActive);

  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) load();
  });

  setInterval(() => {
    if (!document.hidden) load();
  }, 60000);

  paint();
  load();
}

function setupControls() {
  applyScheme(store.scheme());
  applyTheme(store.theme());
  const themeButton = document.getElementById('theme-toggle');
  themeButton?.addEventListener('click', () => {
    const theme = store.toggleTheme();
    applyTheme(theme);
    ui.toast(theme === 'dark' ? '已切换为暗色模式' : '已切换为亮色模式', 'info', 1600);
    renderRoute();
  });

  const schemeButton = document.getElementById('scheme-toggle');
  schemeButton?.addEventListener('click', () => {
    const scheme = store.toggleScheme();
    applyScheme(scheme);
    ui.toast(scheme === 'cn' ? '已切换为中式配色：红涨绿跌' : '已切换为美式配色：绿涨红跌');
    renderRoute();
  });

  const refreshButton = document.getElementById('refresh-btn');
  refreshButton?.addEventListener('click', async () => {
    refreshButton.classList.add('is-spinning');
    await renderRoute();
    setTimeout(() => refreshButton.classList.remove('is-spinning'), 500);
    ui.toast('已请求最新数据', 'info', 1800);
  });
}

window.addEventListener('hashchange', renderRoute);
window.addEventListener('resize', () => charts.resizeAll());

document.addEventListener('visibilitychange', () => {
  if (!document.hidden) charts.resizeAll();
});

setupSidebar();
setupControls();
setupSearch();
setupClock();
renderRoute();

if (!location.hash) {
  const date = todayCn();
  document.documentElement.dataset.date = date;
}
