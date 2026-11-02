import { api } from '../api.js';
import { store } from '../store.js';
import * as ui from '../ui.js';
import * as charts from '../charts.js';
import { $, $$, esc, fmtDate, fmtNum, fmtPct, fmtPrice, tone } from '../utils.js';
import { asOfBadge, viewHead } from './common.js';

export const meta = {
  title: '自选研究',
  eyebrow: 'WATCHLIST',
};

const RANGES = ['3M', '6M', '1Y'];
const RANGE_LABELS = { '3M': '3 个月', '6M': '6 个月', '1Y': '1 年' };
const SORTS = {
  default: { label: '自选顺序' },
  change: { label: '当日涨跌' },
  m1: { label: '近 1 月' },
  m3: { label: '近 3 月' },
  ytd: { label: '年初至今' },
  rsi: { label: 'RSI' },
  from_high: { label: '距 52 周高' },
  relative: { label: '相对 SPY' },
};

function summaryCard(label, value, sub, extra = '') {
  return `<div class="watch-summary-card">
    <span>${esc(label)}</span>
    <strong>${value}</strong>
    <small>${sub}</small>
    ${extra}
  </div>`;
}

function breadthRow(label, value) {
  const safe = Number.isFinite(Number(value)) ? Number(value) : 0;
  return `<div class="watch-breadth-row">
    <div><span>${esc(label)}</span><b>${fmtNum(safe, 0)}%</b></div>
    <div class="watch-breadth-track"><i style="width:${Math.min(100, Math.max(0, safe))}%"></i></div>
  </div>`;
}

function sectorRows(sectors) {
  if (!sectors?.length) return '<p class="field-hint">行业分布暂不可用。</p>';
  const peak = Math.max(...sectors.map((item) => Number(item.weight) || 0), 1);
  return sectors.slice(0, 7).map((item) => `
    <div class="watch-sector-row">
      <div><span>${esc(item.name)}</span><small>${item.count} 只</small></div>
      <div class="watch-sector-track"><i style="width:${Math.min(100, (Number(item.weight) || 0) / peak * 100)}%"></i></div>
      <b class="${tone(item.avg_change_pct)}">${fmtPct(item.avg_change_pct)}</b>
    </div>`).join('');
}

function signalList(items) {
  const signals = [];
  (items || []).forEach((item) => {
    (item.signals || []).forEach((signal) => {
      if (signal.tone === 'neutral') return;
      signals.push({ symbol: item.symbol, ...signal });
    });
  });
  if (!signals.length) return '<p class="field-hint">当前没有触发显著的技术标签。</p>';
  return signals.slice(0, 8).map((signal) => `
    <div class="watch-signal ${esc(signal.tone || 'neutral')}">
      <span class="watch-signal-dot"></span>
      <b>${esc(signal.symbol)}</b>
      <span>${esc(signal.label)}</span>
    </div>`).join('');
}

function sortingButton(key, label, state) {
  const active = state.sort === key;
  return `<button type="button" class="watch-sort ${active ? 'active' : ''}" data-sort="${key}" aria-pressed="${active}">${esc(label)}${active ? `<i>${state.dir > 0 ? '↑' : '↓'}</i>` : ''}</button>`;
}

function stockRow(item, state) {
  const change = Number(item.change_pct);
  const tags = (item.signals || []).filter((signal) => signal.tone !== 'neutral').slice(0, 2);
  return `<tr class="clickable" data-watch-symbol="${esc(item.symbol)}">
    <td>
      <div class="sym-cell">
        <div>
          <div class="sym">${esc(item.symbol)}</div>
          <div class="nm" title="${esc(item.name || '')}">${esc(item.name || item.industry || '—')}</div>
          ${tags.length ? `<div class="watch-row-tags">${tags.map((signal) => `<span class="${esc(signal.tone)}">${esc(signal.label)}</span>`).join('')}</div>` : ''}
        </div>
      </div>
    </td>
    <td class="num-cell"><b>${fmtPrice(item.price)}</b><small class="${tone(change)}">${fmtPct(change)}</small></td>
    <td class="num-cell ${tone(item.return_1m)}">${fmtPct(item.return_1m)}</td>
    <td class="num-cell ${tone(item.return_3m)}">${fmtPct(item.return_3m)}</td>
    <td class="num-cell ${tone(item.ytd)}">${fmtPct(item.ytd)}</td>
    <td class="num-cell">${fmtNum(item.rsi14, 1)}</td>
    <td class="num-cell ${tone(item.relative_3m)}">${fmtPct(item.relative_3m)}</td>
    <td class="num-cell ${tone(item.from_high_52w)}">${fmtPct(item.from_high_52w)}</td>
    <td><span class="watch-trend ${item.above_ma200 ? 'up' : 'down'}">${item.above_ma200 ? 'MA200 上方' : 'MA200 下方'}</span></td>
    <td><div class="watch-spark" data-spark="${esc(item.symbol)}"></div></td>
    <td><button type="button" class="watch-row-remove" data-watch-remove="${esc(item.symbol)}" title="从自选移除" aria-label="从自选移除 ${esc(item.symbol)}">${ui.icon('x', 11)}</button></td>
  </tr>`;
}

function sortItems(items, state) {
  if (!items.length) return [];
  if (state.sort === 'default') return items;
  const key = state.sort;
  const value = (item) => {
    if (key === 'change') return Number(item.change_pct);
    if (key === 'm1') return Number(item.return_1m);
    if (key === 'm3') return Number(item.return_3m);
    if (key === 'ytd') return Number(item.ytd);
    if (key === 'rsi') return Number(item.rsi14);
    if (key === 'from_high') return Number(item.from_high_52w);
    return Number(item.relative_3m);
  };
  return [...items].sort((a, b) => {
    const av = value(a);
    const bv = value(b);
    if (!Number.isFinite(av)) return 1;
    if (!Number.isFinite(bv)) return -1;
    return (av - bv) * state.dir;
  });
}

function renderTable(payload, state) {
  const items = sortItems(payload.items || [], state);
  if (!items.length) return ui.emptyState('暂无自选分析', '先在上方添加股票，或检查行情源是否可用。');
  return `<div class="table-wrap watch-table-wrap">
    <table class="data-table watch-table">
      <thead><tr>
        <th>标的</th>
        <th>${sortingButton('change', '最新 / 当日', state)}</th>
        <th>${sortingButton('m1', '近 1 月', state)}</th>
        <th>${sortingButton('m3', '近 3 月', state)}</th>
        <th>${sortingButton('ytd', '年初至今', state)}</th>
        <th>${sortingButton('rsi', 'RSI', state)}</th>
        <th>${sortingButton('relative', '相对 SPY · 3M', state)}</th>
        <th>${sortingButton('from_high', '距 52 周高', state)}</th>
        <th>趋势</th>
        <th>近 3 月走势</th>
        <th></th>
      </tr></thead>
      <tbody>${items.map((item) => stockRow(item, state)).join('')}</tbody>
    </table>
  </div>`;
}

export async function mount(root, params, ctx) {
  const { signal, isActive, navigate } = ctx;
  const state = {
    range: RANGES.includes(params.range) ? params.range : '3M',
    sort: 'default',
    dir: -1,
    payload: null,
    busy: false,
    disposed: false,
    token: 0,
  };

  root.innerHTML = `
    <section class="view">
      ${viewHead({
        eyebrow: meta.eyebrow,
        title: '自选研究',
        sub: '把关注的标的放在一起，观察相对强弱、趋势结构、尾部风险与相关性。',
        actions: '<span data-watch-asof><span class="pill info">本地自选</span></span>',
      })}
      <section class="panel watchlist-command">
        <div class="panel-body">
          <form class="watchlist-add" data-watch-form>
            <div class="watchlist-add-box">
              ${ui.icon('search', 15)}
              <input type="text" maxlength="10" autocomplete="off" spellcheck="false" placeholder="添加股票代码，如 AMD" aria-label="添加自选代码" data-watch-input>
            </div>
            <button class="btn small" type="submit">${ui.icon('plus', 13)}加入自选</button>
          </form>
          <div class="watchlist-toolbar">
            <div class="seg" data-watch-range>${RANGES.map((range) => `<button type="button" data-range="${range}" class="${range === state.range ? 'active' : ''}">${range}</button>`).join('')}</div>
            <div class="watchlist-actions">
              <button type="button" class="btn small ghost" data-watch-portfolio>${ui.icon('briefcase', 13)}构建组合</button>
              <button type="button" class="btn small ghost" data-watch-compare>${ui.icon('compare', 13)}对比前 6 只</button>
            </div>
          </div>
        </div>
      </section>
      <div data-watch-results>${ui.loadingInline('正在分析自选股…')}</div>
    </section>`;

  const results = $('[data-watch-results]', root);
  const asOf = $('[data-watch-asof]', root);
  const input = $('[data-watch-input]', root);
  let controller = null;

  function setBusy(busy) {
    state.busy = busy;
    $$('[data-watch-range] button, [data-watch-compare], [data-watch-portfolio]', root).forEach((button) => {
      button.disabled = busy;
    });
    const submit = $('[data-watch-form] button[type="submit"]', root);
    if (submit) submit.disabled = busy;
  }

  function render(payload) {
    state.payload = payload;
    const summary = payload.summary || {};
    const items = payload.items || [];
    const sectors = payload.sectors || summary.sectors || [];
    const perf = payload.performance || {};
    const strongest = [...items].sort((a, b) => Number(b.return_1m || -Infinity) - Number(a.return_1m || -Infinity))[0];
    const weakest = [...items].sort((a, b) => Number(a.return_1m || Infinity) - Number(b.return_1m || Infinity))[0];
    asOf.innerHTML = `${asOfBadge(payload.as_of)}<span class="pill info">${summary.count || items.length} 只自选</span>`;
    const warnings = payload.errors?.length || payload.warnings?.length
      ? ui.warnBanner([...(payload.errors || []), ...(payload.warnings || [])])
      : '';

    if (!items.length) {
      results.innerHTML = `${warnings}<section class="panel">${ui.emptyState('自选里还没有股票', '在上方输入代码加入自选，或从个股页点击“加入自选”。')}</section>`;
      return;
    }

    results.innerHTML = `
      ${warnings}
      <div class="watch-summary-grid">
        ${summaryCard('自选标的', `${summary.count || items.length}`, `${summary.advancers || 0} 涨 · ${summary.decliners || 0} 跌`, `<div class="watch-mini-breadth"><i style="width:${summary.count ? (summary.advancers / summary.count) * 100 : 0}%"></i></div>`)}
        ${summaryCard(`等权自选 · ${RANGE_LABELS[state.range]}`, fmtPct(summary.equal_weight_return), `中位数 1 月 ${fmtPct(summary.median_return_1m)}`)}
        ${summaryCard('站上 200 日均线', summary.breadth_above_ma200 === null || summary.breadth_above_ma200 === undefined ? '—' : `${fmtNum(summary.breadth_above_ma200, 0)}%`, `MA20 ${fmtNum(summary.breadth_above_ma20, 0)}% · MA50 ${fmtNum(summary.breadth_above_ma50, 0)}%`)}
        ${summaryCard('平均相关性', fmtNum(summary.avg_correlation, 2), `离散度 ${fmtNum(summary.dispersion, 2)}% · 自选内部`) }
      </div>

      <div class="watch-hero-grid">
        <section class="panel">
          <div class="panel-head">
            <div class="panel-title">自选等权指数 <span class="sub">起点 100 · 对照 ${esc(payload.benchmark || 'SPY')}</span></div>
          </div>
          <div class="chart-body">
            ${perf.dates?.length ? '<div class="chart" data-watch-perf style="height:300px"></div>' : ui.emptyState('暂无共同走势', '自选标的的共同历史不足。')}
          </div>
        </section>
        <section class="panel watch-structure">
          <div class="panel-head"><div class="panel-title">结构观察 <span class="sub">行业构成与市场宽度</span></div></div>
          <div class="panel-body">
            <div class="watch-structure-block">
              <div class="field-label">行业分布 <span>等权口径</span></div>
              ${sectorRows(sectors)}
            </div>
            <div class="watch-structure-block">
              <div class="field-label">趋势广度</div>
              ${breadthRow('高于 20 日均线', summary.breadth_above_ma20)}
              ${breadthRow('高于 50 日均线', summary.breadth_above_ma50)}
              ${breadthRow('高于 200 日均线', summary.breadth_above_ma200)}
            </div>
            <div class="watch-ranking">
              <div><span>最强 1 月</span>${strongest ? `<b>${esc(strongest.symbol)}</b><em class="${tone(strongest.return_1m)}">${fmtPct(strongest.return_1m)}</em>` : '—'}</div>
              <div><span>最弱 1 月</span>${weakest ? `<b>${esc(weakest.symbol)}</b><em class="${tone(weakest.return_1m)}">${fmtPct(weakest.return_1m)}</em>` : '—'}</div>
            </div>
          </div>
        </section>
      </div>

      <section class="panel section-gap">
        <div class="panel-head">
          <div class="panel-title">自选明细 <span class="sub">点击列名排序 · 点击行进入个股研究</span></div>
          <div class="panel-actions"><span class="field-hint">${esc(RANGE_LABELS[state.range])}等权指数</span></div>
        </div>
        <div class="panel-body flush">${renderTable(payload, state)}</div>
      </section>

      <div class="watch-bottom-grid">
        <section class="panel">
          <div class="panel-head"><div class="panel-title">相关性矩阵 <span class="sub">共同日收益 · 近 1 年</span></div></div>
          <div class="panel-body">
            ${payload.correlation?.symbols?.length > 1 ? '<div class="chart" data-watch-corr style="height:auto"></div>' : ui.emptyState('样本不足', '至少需要两只拥有足够重合历史的标的。')}
          </div>
        </section>
        <section class="panel">
          <div class="panel-head"><div class="panel-title">技术标签 <span class="sub">不做综合评分</span></div></div>
          <div class="panel-body watch-signal-list">${signalList(items)}</div>
        </section>
      </div>`;

    if (perf.dates?.length) {
      charts.performanceChart($('[data-watch-perf]', results), {
        dates: perf.dates,
        series: { watchlist: perf.equal_weight || [], benchmark: perf.benchmark || [] },
        labels: { watchlist: '自选等权', benchmark: payload.benchmark || 'SPY' },
      });
    }
    if (payload.correlation?.symbols?.length > 1) {
      charts.correlationHeatmap($('[data-watch-corr]', results), payload.correlation);
    }
    items.forEach((item) => {
      const el = $(`[data-spark="${item.symbol}"]`, results);
      if (el) charts.sparkline(el, item.spark || [], (item.change_pct || 0) >= 0);
    });
    setBusy(false);
  }

  async function analyze() {
    const symbols = store.watchlist();
    if (!symbols.length) {
      state.payload = null;
      asOf.innerHTML = '<span class="pill info">本地自选</span>';
      results.innerHTML = `<section class="panel">${ui.emptyState('自选里还没有股票', '在上方输入代码加入自选，或从个股页点击“加入自选”。')}</section>`;
      return;
    }
    const token = ++state.token;
    controller?.abort();
    controller = new AbortController();
    setBusy(true);
    if (!state.payload) results.innerHTML = `<section class="panel">${ui.loadingInline('正在分析自选股…')}</section>`;
    try {
      const payload = await api.get(
        `/api/watchlist/analyze?symbols=${encodeURIComponent(symbols.join(','))}&range=${encodeURIComponent(state.range)}`,
        { signal: controller.signal, timeout: 120000 },
      );
      if (token !== state.token || !isActive() || state.disposed) return;
      render(payload);
    } catch (error) {
      if (error?.name === 'AbortError' || state.disposed || token !== state.token) return;
      results.innerHTML = `<section class="panel">${ui.errorPanel(error.message || '自选分析加载失败')}</section>`;
      ui.bindRetry(results, analyze);
      setBusy(false);
    }
  }

  async function addSymbol(raw) {
    const code = String(raw || '').trim().toUpperCase();
    if (!/^[A-Z][A-Z0-9.\-]{0,9}$/.test(code)) {
      ui.toast('请输入有效的美股代码', 'warn');
      return;
    }
    if (store.isWatched(code)) {
      ui.toast(`${code} 已在自选中`, 'info');
      return;
    }
    if (store.watchlist().length >= 15) {
      ui.toast('自选最多 15 只，请先移除部分标的', 'warn');
      return;
    }
    const submit = $('[data-watch-form] button[type="submit"]', root);
    if (submit) submit.disabled = true;
    try {
      const payload = await api.get(`/api/quotes?symbols=${encodeURIComponent(code)}`, { timeout: 20000 });
      const item = (payload.items || []).find((row) => row.symbol === code) || (payload.items || [])[0];
      if (!item) throw new Error(`未找到代码 ${code}`);
      store.addWatch(item.symbol);
      input.value = '';
      ui.toast(`已加入 ${item.symbol}`, 'success', 1500);
    } catch (error) {
      ui.toast(error?.message || '添加自选失败', 'error');
    } finally {
      if (submit) submit.disabled = false;
    }
  }

  $('[data-watch-form]', root).addEventListener('submit', (event) => {
    event.preventDefault();
    addSymbol(input.value);
  });

  $('[data-watch-range]', root).addEventListener('click', (event) => {
    const button = event.target.closest('[data-range]');
    if (!button || state.busy || button.dataset.range === state.range) return;
    state.range = button.dataset.range;
    $$('[data-watch-range] button', root).forEach((item) => item.classList.toggle('active', item.dataset.range === state.range));
    analyze();
  });

  $('[data-watch-compare]', root).addEventListener('click', () => {
    const symbols = store.watchlist().slice(0, 6);
    if (symbols.length < 2) {
      ui.toast('至少需要 2 只自选才能对比', 'warn');
      return;
    }
    navigate(`#/compare?symbols=${encodeURIComponent(symbols.join(','))}`);
  });

  $('[data-watch-portfolio]', root).addEventListener('click', () => {
    const symbols = store.watchlist();
    if (!symbols.length) {
      ui.toast('先添加至少一只自选', 'warn');
      return;
    }
    navigate(`#/portfolio?symbols=${encodeURIComponent(symbols.join(','))}`);
  });

  results.addEventListener('click', (event) => {
    const remove = event.target.closest('[data-watch-remove]');
    if (remove) {
      event.stopPropagation();
      store.removeWatch(remove.dataset.watchRemove);
      ui.toast(`已从自选移除 ${remove.dataset.watchRemove}`, 'info', 1500);
      return;
    }
    const sort = event.target.closest('[data-sort]');
    if (sort) {
      const key = sort.dataset.sort;
      if (state.sort === key) state.dir *= -1;
      else {
        state.sort = key;
        state.dir = -1;
      }
      if (state.payload) {
        const table = $('.watch-table', results);
        if (table) {
          const wrap = table.closest('.watch-table-wrap');
          $$('.watch-spark', results).forEach((el) => charts.clear(el));
          wrap.outerHTML = renderTable(state.payload, state);
          (state.payload.items || []).forEach((item) => {
            const el = $(`[data-spark="${item.symbol}"]`, results);
            if (el) charts.sparkline(el, item.spark || [], (item.change_pct || 0) >= 0);
          });
        }
      }
      return;
    }
    if (event.target.closest('button, a, input, select')) return;
    const row = event.target.closest('[data-watch-symbol]');
    if (row) navigate(`#/stock/${encodeURIComponent(row.dataset.watchSymbol)}`);
  });

  const onStore = (event) => {
    if (event.detail?.type !== 'watchlist' || state.disposed) return;
    analyze();
  };
  window.addEventListener('starmap:store', onStore);
  analyze();

  return () => {
    state.disposed = true;
    state.token += 1;
    controller?.abort();
    window.removeEventListener('starmap:store', onStore);
  };
}
