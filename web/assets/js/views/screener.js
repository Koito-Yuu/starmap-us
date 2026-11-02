import { api } from '../api.js';
import { store } from '../store.js';
import * as ui from '../ui.js';
import {
  $,
  $$,
  debounce,
  downloadCSV,
  esc,
  fmtCompact,
  fmtInt,
  fmtNum,
  fmtPct,
  fmtPrice,
  tone,
} from '../utils.js';
import { asOfBadge, viewHead } from './common.js';

export const meta = {
  title: '智能选股',
  eyebrow: 'SCREENER / US EQUITY',
};

const PAGE_SIZE = 50;
const SORT_COLUMNS = {
  symbol: { label: '代码', numeric: false },
  price: { label: '价格', numeric: true },
  change_pct: { label: '涨跌幅', numeric: true },
  market_cap: { label: '总市值', numeric: true },
  pe: { label: 'PE', numeric: true },
  pb: { label: 'PB', numeric: true },
  dividend_yield: { label: '股息率', numeric: true },
  chg_60d: { label: '60日', numeric: true },
  chg_ytd: { label: '年内', numeric: true },
};

const DEFAULT_FILTERS = {
  keyword: '',
  industry: '',
  mcapMin: '',
  peMin: '',
  peMax: '',
  pbMax: '',
  yieldMin: '',
  chg60Min: '',
  chg60Max: '',
  chgYtdMin: '',
  watchOnly: false,
};

function toNumber(value) {
  if (value === '' || value === null || value === undefined) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function sourceLabel(source) {
  if (source === 'nasdaq_screener') return 'Nasdaq 备用快照';
  if (source === 'eastmoney+nasdaq') return '东方财富缓存 + Nasdaq';
  return '东方财富全市场';
}

function sortArrow(key, state) {
  if (state.sortKey !== key) return '';
  return `<span class="sort-arrow">${state.sortDir === 'asc' ? '▲' : '▼'}</span>`;
}

function pagerButtons(page, pages) {
  if (pages <= 1) return '';
  const numbers = new Set([1, pages, page - 1, page, page + 1]);
  if (page <= 3) [2, 3, 4].forEach((item) => numbers.add(item));
  if (page >= pages - 2) [pages - 3, pages - 2, pages - 1].forEach((item) => numbers.add(item));
  const valid = Array.from(numbers).filter((item) => item >= 1 && item <= pages).sort((a, b) => a - b);
  const bits = [`<button type="button" data-page="${page - 1}" ${page <= 1 ? 'disabled' : ''}>‹</button>`];
  let previous = 0;
  valid.forEach((item) => {
    if (previous && item - previous > 1) bits.push('<span class="pager-info">…</span>');
    bits.push(`<button type="button" data-page="${item}" class="${item === page ? 'active' : ''}">${item}</button>`);
    previous = item;
  });
  bits.push(`<button type="button" data-page="${page + 1}" ${page >= pages ? 'disabled' : ''}>›</button>`);
  bits.push(`<span class="pager-info">共 ${pages} 页</span>`);
  return bits.join('');
}

export async function mount(root, params, ctx) {
  const { signal, isActive, navigate } = ctx;
  const state = {
    items: [],
    filters: { ...DEFAULT_FILTERS },
    preset: '',
    sortKey: 'market_cap',
    sortDir: 'desc',
    page: 1,
    hasFundamentals: false,
    source: '',
    totalMarket: 0,
    updatedAt: '',
    disposed: false,
  };

  root.innerHTML = `
    <section class="view">
      ${viewHead({
        eyebrow: meta.eyebrow,
        title: '智能选股',
        sub: '从全市场快照中按估值、动量、股息与行业维度筛选标的。',
        actions: '<span class="as-of"><span class="dot"></span>加载全市场快照…</span>',
      })}
      <div class="panel" data-loading>${ui.loadingInline('正在加载全市场快照（约 14,000 只，首次抓取可能需要数十秒）…')}</div>
    </section>`;

  let data;
  let presets = [];
  try {
    [data, presets] = await Promise.all([
      api.get('/api/screener/universe?limit=14000', { signal, timeout: 180000 }),
      api.get('/api/screener/presets', { signal, timeout: 30000 }).then((payload) => payload.items || []),
    ]);
  } catch (error) {
    if (error?.name === 'AbortError') return undefined;
    root.innerHTML = `
      <section class="view">
        ${viewHead({ eyebrow: meta.eyebrow, title: '智能选股', sub: '未能加载全市场快照。' })}
        <div class="panel">${ui.errorPanel(error.message || '选股数据加载失败')}</div>
      </section>`;
    ui.bindRetry(root, () => ctx.reload());
    return undefined;
  }
  if (!isActive() || state.disposed) return undefined;

  state.items = (data.items || []).filter((item) => !item.is_etf);
  state.source = data.source || 'eastmoney';
  state.totalMarket = data.total_market || state.items.length;
  state.updatedAt = data.updated_at || '';
  state.hasFundamentals = state.items.some(
    (item) => item.pe !== null || item.pb !== null || item.dividend_yield !== null || item.chg_ytd !== null,
  );

  const industries = Array.from(new Set(state.items.map((item) => item.industry).filter(Boolean)))
    .map((name) => ({ name, count: state.items.filter((item) => item.industry === name).length }))
    .sort((a, b) => b.count - a.count);

  const coverage = state.source === 'nasdaq_screener'
    ? `Nasdaq 备用快照 ${fmtInt(state.totalMarket)} 只标的 · 已载入 ${fmtInt(state.items.length)} 只可筛选标的`
    : `全市场 ${fmtInt(state.totalMarket)} 只美股 · 已载入 ${fmtInt(state.items.length)} 只可筛选标的`;
  root.innerHTML = `
    <section class="view">
      ${viewHead({
        eyebrow: meta.eyebrow,
        title: '智能选股',
        sub: coverage,
        actions: `${asOfBadge(state.updatedAt)}<span class="pill info">${esc(sourceLabel(state.source))}</span>`,
      })}
      ${
        state.source === 'eastmoney+nasdaq'
          ? ui.warnBanner('东方财富快照暂不可用：前 3,000 只沿用最近缓存，其余来自 Nasdaq 补充；估值与动量字段覆盖不完整。上游恢复后重新加载页面将抓取完整快照。')
          : state.hasFundamentals
            ? ''
            : ui.warnBanner('当前快照来自备用数据源，PE、PB、股息与动量字段不可用，仅支持行情与行业筛选。')
      }

      <div class="preset-row" data-presets>
        ${presets
          .map(
            (preset) => `
            <button type="button" class="preset-card" data-preset="${esc(preset.id)}" title="${esc(preset.description || '')}">
              <span class="p-title">${esc(preset.title)}</span>
              <span class="p-desc">${esc(preset.description || '')}</span>
            </button>`,
          )
          .join('')}
        <button type="button" class="preset-card" data-preset=""><span class="p-title">全部标的</span><span class="p-desc">清空所有筛选条件</span></button>
      </div>

      <section class="panel screener-filter-panel">
        <div class="panel-head">
          <div class="panel-title">筛选条件 <span class="sub">条件实时生效</span></div>
          <div class="panel-actions">
            <button type="button" class="btn small ghost" data-watch-only>${ui.icon('star', 13)}仅看自选</button>
            <button type="button" class="btn small ghost" data-reset>${ui.icon('refresh', 13)}重置</button>
          </div>
        </div>
        <div class="panel-body">
          <div class="filter-grid">
            <div class="field">
              <label>关键词</label>
              <input class="input" type="text" data-filter="keyword" placeholder="代码 / 公司名" autocomplete="off" spellcheck="false">
            </div>
            <div class="field">
              <label>行业</label>
              <select class="input" data-filter="industry">
                <option value="">全部行业</option>
                ${industries
                  .slice(0, 120)
                  .map((item) => `<option value="${esc(item.name)}">${esc(item.name)}（${item.count}）</option>`)
                  .join('')}
              </select>
            </div>
            <div class="field">
              <label>市值下限（亿美元）</label>
              <input class="input" type="number" min="0" step="10" data-filter="mcapMin" placeholder="如 100" ${state.hasFundamentals ? '' : 'disabled'}>
            </div>
            <div class="field">
              <label>PE 下限</label>
              <input class="input" type="number" step="1" data-filter="peMin" placeholder="不限" ${state.hasFundamentals ? '' : 'disabled'}>
            </div>
            <div class="field">
              <label>PE 上限</label>
              <input class="input" type="number" step="1" data-filter="peMax" placeholder="不限" ${state.hasFundamentals ? '' : 'disabled'}>
            </div>
            <div class="field">
              <label>PB 上限</label>
              <input class="input" type="number" step="0.5" data-filter="pbMax" placeholder="不限" ${state.hasFundamentals ? '' : 'disabled'}>
            </div>
            <div class="field">
              <label>股息率下限（%）</label>
              <input class="input" type="number" min="0" step="0.5" data-filter="yieldMin" placeholder="不限" ${state.hasFundamentals ? '' : 'disabled'}>
            </div>
            <div class="field">
              <label>60 日涨幅下限（%）</label>
              <input class="input" type="number" step="5" data-filter="chg60Min" placeholder="不限" ${state.hasFundamentals ? '' : 'disabled'}>
            </div>
            <div class="field">
              <label>60 日涨幅上限（%）</label>
              <input class="input" type="number" step="5" data-filter="chg60Max" placeholder="如 -10" title="用于筛选超跌标的，可留空" ${state.hasFundamentals ? '' : 'disabled'}>
            </div>
            <div class="field">
              <label>年内涨幅下限（%）</label>
              <input class="input" type="number" step="5" data-filter="chgYtdMin" placeholder="不限" ${state.hasFundamentals ? '' : 'disabled'}>
            </div>
          </div>
          <div class="filter-actions" style="margin-top:12px">
            <span class="field-hint">行业分类与估值字段随数据源而变，行情可能延迟。</span>
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="result-bar">
          <div class="result-count">匹配 <b data-count>0</b> 只标的 <span data-coverage></span></div>
          <div class="result-actions">
            <button type="button" class="btn small" data-export>${ui.icon('download', 13)}导出 CSV</button>
            <button type="button" class="btn small ghost" data-refresh>${ui.icon('refresh', 13)}刷新快照</button>
          </div>
        </div>
        <div class="screener-table-wrap" data-table-wrap>
          <table class="data-table">
            <thead>
              <tr>
                <th style="width:34px"></th>
                <th class="sortable text-left" data-sort="symbol">代码${sortArrow('symbol', state)}</th>
                <th class="text-left">行业</th>
                <th class="sortable" data-sort="price">价格${sortArrow('price', state)}</th>
                <th class="sortable" data-sort="change_pct">涨跌幅${sortArrow('change_pct', state)}</th>
                <th class="sortable" data-sort="market_cap">总市值${sortArrow('market_cap', state)}</th>
                <th class="sortable" data-sort="pe">PE${sortArrow('pe', state)}</th>
                <th class="sortable" data-sort="pb">PB${sortArrow('pb', state)}</th>
                <th class="sortable" data-sort="dividend_yield">股息率${sortArrow('dividend_yield', state)}</th>
                <th class="sortable" data-sort="chg_60d">60日${sortArrow('chg_60d', state)}</th>
                <th class="sortable" data-sort="chg_ytd">年内${sortArrow('chg_ytd', state)}</th>
              </tr>
            </thead>
            <tbody data-tbody></tbody>
          </table>
        </div>
        <div class="pager" data-pager></div>
      </section>
    </section>`;

  const tbody = $('[data-tbody]', root);
  const pager = $('[data-pager]', root);
  const countEl = $('[data-count]', root);
  const coverageEl = $('[data-coverage]', root);

  if (coverageEl) {
    const peCount = state.items.filter((item) => item.pe !== null).length;
    coverageEl.textContent = peCount ? `· PE 覆盖 ${Math.round((peCount / state.items.length) * 100)}%` : '';
  }

  function filtered() {
    const f = state.filters;
    const keyword = f.keyword.trim().toLowerCase();
    const mcapMin = toNumber(f.mcapMin);
    const peMin = toNumber(f.peMin);
    const peMax = toNumber(f.peMax);
    const pbMax = toNumber(f.pbMax);
    const yieldMin = toNumber(f.yieldMin);
    const chg60Min = toNumber(f.chg60Min);
    const chg60Max = toNumber(f.chg60Max);
    const chgYtdMin = toNumber(f.chgYtdMin);
    const watch = f.watchOnly ? new Set(store.watchlist()) : null;
    const rows = state.items.filter((item) => {
      if (watch && !watch.has(item.symbol)) return false;
      if (keyword && !`${item.symbol} ${item.name}`.toLowerCase().includes(keyword)) return false;
      if (f.industry && item.industry !== f.industry) return false;
      if (mcapMin !== null && (item.market_cap === null || item.market_cap < mcapMin * 1e8)) return false;
      if (peMin !== null && (item.pe === null || item.pe < peMin)) return false;
      if (peMax !== null && (item.pe === null || item.pe > peMax)) return false;
      if (pbMax !== null && (item.pb === null || item.pb <= 0 || item.pb > pbMax)) return false;
      if (yieldMin !== null && (item.dividend_yield === null || item.dividend_yield < yieldMin)) return false;
      if (chg60Min !== null && (item.chg_60d === null || item.chg_60d < chg60Min)) return false;
      if (chg60Max !== null && (item.chg_60d === null || item.chg_60d > chg60Max)) return false;
      if (chgYtdMin !== null && (item.chg_ytd === null || item.chg_ytd < chgYtdMin)) return false;
      return true;
    });
    const key = state.sortKey;
    const dir = state.sortDir === 'asc' ? 1 : -1;
    rows.sort((left, right) => {
      if (key === 'symbol') return left.symbol.localeCompare(right.symbol) * dir;
      const a = left[key];
      const b = right[key];
      const aMissing = a === null || a === undefined || !Number.isFinite(Number(a));
      const bMissing = b === null || b === undefined || !Number.isFinite(Number(b));
      if (aMissing && bMissing) return 0;
      if (aMissing) return 1;
      if (bMissing) return -1;
      return (Number(a) - Number(b)) * dir;
    });
    return rows;
  }

  function renderTable() {
    const rows = filtered();
    const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
    state.page = Math.min(state.page, pages);
    const start = (state.page - 1) * PAGE_SIZE;
    const pageRows = rows.slice(start, start + PAGE_SIZE);
    countEl.textContent = fmtInt(rows.length);
    $$('.data-table th.sortable', root).forEach((th) => {
      const arrow = sortArrow(th.dataset.sort, state);
      th.innerHTML = `${SORT_COLUMNS[th.dataset.sort].label}${arrow}`;
    });
    tbody.innerHTML = pageRows.length
      ? pageRows
          .map(
            (item) => `
            <tr class="clickable" data-symbol="${esc(item.symbol)}">
              <td><button type="button" class="star-cell ${store.isWatched(item.symbol) ? 'on' : ''}" data-watch="${esc(item.symbol)}" aria-label="自选 ${esc(item.symbol)}">${ui.starIcon(store.isWatched(item.symbol), 13)}</button></td>
              <td>
                <div class="sym-cell">
                  <div>
                    <div class="sym">${esc(item.symbol)}</div>
                    <div class="nm" title="${esc(item.name || '')}">${esc(item.name || '—')}</div>
                  </div>
                </div>
              </td>
              <td class="dim-cell" style="text-align:left">${esc(item.industry || '—')}</td>
              <td class="num-cell">${fmtPrice(item.price)}</td>
              <td class="${tone(item.change_pct)}">${fmtPct(item.change_pct)}</td>
              <td class="num-cell">$${fmtCompact(item.market_cap)}</td>
              <td>${fmtNum(item.pe, 1)}</td>
              <td>${fmtNum(item.pb, 2)}</td>
              <td>${item.dividend_yield !== null ? fmtPct(item.dividend_yield, 2, false) : '—'}</td>
              <td class="${tone(item.chg_60d)}">${fmtPct(item.chg_60d)}</td>
              <td class="${tone(item.chg_ytd)}">${fmtPct(item.chg_ytd)}</td>
            </tr>`,
          )
          .join('')
      : `<tr><td class="empty-cell" colspan="11">没有符合条件的标的，试试放宽筛选条件。</td></tr>`;
    pager.innerHTML = pagerButtons(state.page, pages);
    pager.style.display = rows.length ? '' : 'none';
  }

  const onKeyword = debounce(() => {
    state.filters.keyword = $('[data-filter="keyword"]', root).value;
    state.page = 1;
    state.preset = '';
    $$('[data-preset]', root).forEach((card) => card.classList.remove('active'));
    renderTable();
  }, 160);

  $$('[data-filter]', root).forEach((input) => {
    const key = input.dataset.filter;
    const handler = () => {
      if (key === 'keyword') return onKeyword();
      state.filters[key] = input.value;
      state.page = 1;
      state.preset = '';
      $$('[data-preset]', root).forEach((card) => card.classList.remove('active'));
      renderTable();
    };
    input.addEventListener(input.tagName === 'SELECT' ? 'change' : 'input', handler);
  });

  $('[data-watch-only]', root).addEventListener('click', (event) => {
    state.filters.watchOnly = !state.filters.watchOnly;
    state.page = 1;
    state.preset = '';
    $$('[data-preset]', root).forEach((card) => card.classList.remove('active'));
    event.currentTarget.classList.toggle('primary', state.filters.watchOnly);
    event.currentTarget.classList.toggle('ghost', !state.filters.watchOnly);
    renderTable();
  });

  function resetFilters() {
    state.filters = { ...DEFAULT_FILTERS };
    state.preset = '';
    state.page = 1;
    $$('[data-filter]', root).forEach((input) => {
      input.value = '';
    });
    const watchButton = $('[data-watch-only]', root);
    watchButton.classList.remove('primary');
    watchButton.classList.add('ghost');
    $$('[data-preset]', root).forEach((card) => card.classList.remove('active'));
    renderTable();
  }

  $('[data-reset]', root).addEventListener('click', resetFilters);

  $$('[data-preset]', root).forEach((card) => {
    card.addEventListener('click', () => {
      const preset = presets.find((item) => item.id === card.dataset.preset);
      if (!preset) {
        resetFilters();
        return;
      }
      state.filters = { ...DEFAULT_FILTERS };
      const map = {
        mcapMin: 'mcapMin',
        peMin: 'peMin',
        peMax: 'peMax',
        pbMax: 'pbMax',
        yieldMin: 'yieldMin',
        chg60Min: 'chg60Min',
        chg60Max: 'chg60Max',
        chgYtdMin: 'chgYtdMin',
      };
      Object.entries(preset.filters || {}).forEach(([key, value]) => {
        if (key === 'mcapMin') state.filters.mcapMin = String(value / 1e8);
        else if (map[key] !== undefined) state.filters[key] = String(value);
      });
      $$('[data-filter]', root).forEach((input) => {
        const key = input.dataset.filter;
        input.value = state.filters[key] ?? '';
      });
      state.page = 1;
      state.preset = preset.id;
      $$('[data-preset]', root).forEach((item) => item.classList.toggle('active', item === card));
      renderTable();
    });
  });

  $('[data-export]', root).addEventListener('click', () => {
    const rows = filtered();
    if (!rows.length) {
      ui.toast('当前没有可导出的标的', 'warn');
      return;
    }
    downloadCSV(`starmap-screener-${new Date().toISOString().slice(0, 10)}.csv`, [
      ['代码', '名称', '行业', '价格', '涨跌幅(%)', '总市值(亿美元)', 'PE', 'PB', '股息率(%)', '60日涨幅(%)', '年内涨幅(%)'],
      ...rows.map((item) => [
        item.symbol,
        item.name || '',
        item.industry || '',
        item.price ?? '',
        item.change_pct ?? '',
        item.market_cap ? (item.market_cap / 1e8).toFixed(2) : '',
        item.pe ?? '',
        item.pb ?? '',
        item.dividend_yield ?? '',
        item.chg_60d ?? '',
        item.chg_ytd ?? '',
      ]),
    ]);
    ui.toast(`已导出 ${rows.length} 只标的`, 'success', 2200);
  });

  $('[data-refresh]', root).addEventListener('click', () => ctx.reload());

  root.addEventListener('click', (event) => {
    const watchButton = event.target.closest('[data-watch]');
    if (watchButton) {
      event.stopPropagation();
      const symbol = watchButton.dataset.watch;
      const on = store.toggleWatch(symbol);
      ui.toast(on ? `已添加 ${symbol} 到自选` : `已从自选移除 ${symbol}`, on ? 'success' : 'info', 1800);
      return;
    }
    const sortHeader = event.target.closest('th[data-sort]');
    if (sortHeader) {
      const key = sortHeader.dataset.sort;
      if (state.sortKey === key) state.sortDir = state.sortDir === 'asc' ? 'desc' : 'asc';
      else {
        state.sortKey = key;
        state.sortDir = SORT_COLUMNS[key].numeric ? 'desc' : 'asc';
      }
      renderTable();
      return;
    }
    const pageButton = event.target.closest('[data-page]');
    if (pageButton && !pageButton.disabled) {
      state.page = Number(pageButton.dataset.page) || 1;
      renderTable();
      return;
    }
    if (event.target.closest('a, input, select, button')) return;
    const row = event.target.closest('tr[data-symbol]');
    if (row?.dataset.symbol) navigate(row.dataset.symbol);
  });

  const onWatchStore = (event) => {
    if (event.detail?.type !== 'watchlist' || state.disposed) return;
    if (state.filters.watchOnly) {
      renderTable();
      return;
    }
    $$('[data-watch]', root).forEach((button) => {
      const on = store.isWatched(button.dataset.watch);
      button.classList.toggle('on', on);
      button.innerHTML = ui.starIcon(on, 13);
    });
  };
  window.addEventListener('starmap:store', onWatchStore);

  renderTable();

  return () => {
    state.disposed = true;
    window.removeEventListener('starmap:store', onWatchStore);
  };
}
