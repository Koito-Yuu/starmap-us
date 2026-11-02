import { api } from '../api.js';
import { store } from '../store.js';
import * as ui from '../ui.js';
import * as charts from '../charts.js';
import {
  $,
  $$,
  esc,
  fmtCompact,
  fmtDate,
  fmtInt,
  fmtNum,
  fmtPct,
  fmtPrice,
  tone,
} from '../utils.js';
import { asOfBadge, newsList, viewHead } from './common.js';

export const meta = {
  title: '市场总览',
  eyebrow: 'MARKET PULSE / US',
};

function indexCards(data) {
  if (!data.indices?.length) {
    return `<div class="panel">${ui.emptyState('指数行情暂不可用', '东方财富与腾讯行情接口均未返回数据，请稍后刷新。')}</div>`;
  }
  return data.indices
    .map((item) => {
      const change = Number(item.change_pct);
      return `
        <article class="index-card">
          <div class="index-head">
            <span class="index-name">${esc(item.name)}</span>
            <span class="idx-code">${esc(item.symbol)}</span>
          </div>
          <div class="index-price">${fmtNum(item.price, 2)}</div>
          <div class="index-meta">
            <span class="index-delta ${tone(change)}">
              ${fmtPct(change)}
              <span class="dim">${item.change !== null && item.change !== undefined ? fmtNum(item.change, 2) : ''}</span>
            </span>
            <span class="index-source">${esc(String(item.source || 'EASTMONEY').toUpperCase())}</span>
          </div>
          <div class="idx-spark" data-spark="${esc(item.symbol)}"></div>
        </article>`;
    })
    .join('');
}

function moverRows(items, kind) {
  const list = items || [];
  if (!list.length) {
    return ui.emptyState('暂无榜单数据', '全市场快照仍在刷新，请稍后重试。');
  }
  return list
    .map((item, index) => {
      const change = item.change_pct;
      const third = kind === 'active' ? `${fmtCompact(item.amount)}<small> 美元</small>` : fmtPct(change);
      return `
        <div class="mover-row" data-symbol="${esc(item.symbol)}">
          <div class="mover-id">
            <span class="mover-rank">${String(index + 1).padStart(2, '0')}</span>
            <span class="mover-sym">${esc(item.symbol)}</span>
            <span class="mover-name">${esc(item.name || '')}</span>
          </div>
          <span class="mover-price">${fmtPrice(item.price)}</span>
          <span class="mover-chg ${kind === 'active' ? 'mover-amount' : tone(change)}">${third}</span>
        </div>`;
    })
    .join('');
}

function breadthBlock(data) {
  const breadth = data.breadth || {};
  if (breadth.up_ratio === null || breadth.up_ratio === undefined || !breadth.sample) {
    return ui.emptyState('暂无市场宽度', '全市场涨跌统计暂不可用。');
  }
  const total = breadth.sample || 1;
  const advance = (breadth.advancers / total) * 100;
  const unchanged = (breadth.unchanged / total) * 100;
  const decline = (breadth.decliners / total) * 100;
  return `
    <div class="chart" data-breadth style="height:132px;margin-top:-10px"></div>
    <div class="breadth-stats">
      <div class="breadth-stat"><div class="b-val pos">${fmtInt(breadth.advancers)}</div><div class="b-label">上涨</div></div>
      <div class="breadth-stat"><div class="b-val flat">${fmtInt(breadth.unchanged)}</div><div class="b-label">平盘</div></div>
      <div class="breadth-stat"><div class="b-val neg">${fmtInt(breadth.decliners)}</div><div class="b-label">下跌</div></div>
    </div>
    <div class="breadth-split">
      <span class="adv" style="width:${advance}%"></span>
      <span class="unc" style="width:${unchanged}%"></span>
      <span class="dec" style="width:${decline}%"></span>
    </div>
    <div class="breadth-legend">
      <span>上涨 ${advance.toFixed(1)}%</span>
      <span>中位涨跌 ${fmtPct(breadth.median_change)}</span>
      <span>下跌 ${decline.toFixed(1)}%</span>
    </div>
    <div class="sector-foot"><span>样本 ${fmtInt(breadth.sample)} 只普通股</span><span>上涨占比 ${fmtNum(breadth.up_ratio, 1)}%</span></div>`;
}

function sectorRows(sectors) {
  if (!sectors?.length) {
    return ui.emptyState('板块数据暂不可用', 'SPDR 行业 ETF 行情暂未返回。');
  }
  const maxAbs = Math.max(...sectors.map((item) => Math.abs(Number(item.change_pct) || 0)), 0.5);
  return `
    <div class="sector-list">
      ${sectors
        .map((item) => {
          const change = Number(item.change_pct) || 0;
          const width = Math.max(2, (Math.abs(change) / maxAbs) * 100);
          return `
            <div class="sector-row" data-symbol="${esc(item.symbol)}" title="查看 ${esc(item.etf_name || item.symbol)} 行情">
              <div class="sector-name">${esc(item.name)}<small>${esc(item.symbol)}</small></div>
              <div class="sector-track"><div class="sector-fill ${change >= 0 ? 'pos' : 'neg'}" style="width:${width}%"></div></div>
              <div class="sector-pct ${tone(change)}">${fmtPct(change)}</div>
            </div>`;
        })
        .join('')}
    </div>
    <div class="sector-foot"><span>领涨 ${esc(sectors[0]?.name || '—')}</span><span>领跌 ${esc(sectors[sectors.length - 1]?.name || '—')}</span></div>`;
}

function macroMini(cards) {
  if (!cards?.length) {
    return ui.emptyState('宏观数据暂不可用', 'FRED 序列暂时没有返回数据。');
  }
  return `<div class="macro-mini-grid">${cards
    .map((item) => {
      const decimals = item.decimals ?? 2;
      const delta = item.delta;
      return `
        <button class="macro-mini" type="button" data-macro="${esc(item.id)}" style="text-align:left">
          <div class="m-label">${esc(item.label)}</div>
          <div class="m-value">${fmtNum(item.value, decimals)}<small>${esc(item.unit || '')}</small></div>
          <div class="m-delta">${esc(item.delta_label || '较前值')} <b class="${tone(delta)}">${delta !== null && delta !== undefined ? `${delta > 0 ? '+' : ''}${fmtNum(delta, decimals)}${item.unit || ''}` : '—'}</b></div>
        </button>`;
    })
    .join('')}</div>`;
}

function earningsRows(items) {
  if (!items?.length) {
    return ui.emptyState('暂无财报安排', '未来 7 天没有获取到重点财报日历。');
  }
  return `<div class="earn-list">${items
    .map(
      (item) => `
        <div class="earn-row" data-symbol="${esc(item.symbol)}" title="${esc(`${item.symbol} · ${item.name || ''} · 市值 ${fmtCompact(item.market_cap)}`)}">
          <div class="earn-date">${esc(fmtDate(item.date, 'short'))}<span class="earn-time">${esc(item.time_label || '待定')}</span></div>
          <div class="earn-main">
            <div class="earn-sym">${esc(item.symbol)}</div>
            <div class="earn-name">${esc(item.name || '')}</div>
          </div>
          <div class="earn-eps">EPS 预期 ${fmtNum(item.eps_forecast, 2)}<span class="earn-time">市值 ${fmtCompact(item.market_cap)}</span></div>
        </div>`,
    )
    .join('')}</div>`;
}

function watchTile(item, symbol) {
  if (!item) {
    return `
      <article class="watch-tile" data-symbol="${esc(symbol)}">
        <button class="watch-remove" type="button" data-remove="${esc(symbol)}" title="移出自选">${ui.icon('x', 11)}</button>
        <div class="w-sym">${esc(symbol)}</div>
        <div class="w-name">行情暂不可用</div>
        <div class="w-price"><span>—</span><span class="w-chg flat">—</span></div>
      </article>`;
  }
  return `
    <article class="watch-tile" data-symbol="${esc(item.symbol)}">
      <button class="watch-remove" type="button" data-remove="${esc(item.symbol)}" title="移出自选">${ui.icon('x', 11)}</button>
      <div class="w-sym">${esc(item.symbol)}</div>
      <div class="w-name">${esc(item.name || '')}</div>
      <div class="w-price">
        <span>${fmtPrice(item.price)}</span>
        <span class="w-chg ${tone(item.change_pct)}">${fmtPct(item.change_pct)}</span>
      </div>
    </article>`;
}

export async function mount(root, params, ctx) {
  const { signal, isActive, navigate } = ctx;
  let data;
  try {
    data = await api.get('/api/market/overview', { signal, timeout: 120000 });
  } catch (error) {
    if (error?.name === 'AbortError') return undefined;
    root.innerHTML = `<section class="view"><div class="panel">${ui.errorPanel(error.message || '市场总览加载失败')}</div></section>`;
    ui.bindRetry(root, () => ctx.reload());
    return undefined;
  }
  if (!isActive()) return undefined;

  const status = data.status || {};
  const universe = data.universe || {};
  const sparkLength = Math.max(
    0,
    ...Object.values(data.sparklines || {}).map((values) => (Array.isArray(values) ? values.length : 0)),
  );
  const warnings = ui.warnBanner(data.warnings || []);
  const actions = `
    ${asOfBadge(data.as_of)}
    <span class="pill ${status.state === 'open' ? 'positive' : 'neutral'}">${esc(status.label || '休市')}</span>
    <a class="btn small" href="#/screener">${ui.icon('filter', 13)}智能选股</a>`;

  root.innerHTML = `
    <section class="view">
      ${viewHead({
        eyebrow: 'MARKET PULSE / US',
        title: '市场总览',
        sub: '指数、全市场热力、资金异动、板块轮动与宏观环境，一屏掌握美股当日脉搏。',
        actions,
      })}
      ${warnings}

      <div class="index-grid">${indexCards(data)}</div>

      <div class="overview-grid">
        <div class="col-stack">
          <section class="panel">
            <div class="panel-head">
              <div class="panel-title">
                市场热力图
                <span class="tag">${esc(universe.source === 'nasdaq_screener' ? 'NASDAQ SCREENER' : universe.source === 'eastmoney+nasdaq' ? 'EASTMONEY + NASDAQ' : 'EASTMONEY')}</span>
                <span class="sub">按市值加权 · 点击进入个股</span>
              </div>
              <div class="panel-actions">
                <span class="badge">${fmtInt(universe.sample || 0)} 只样本</span>
              </div>
            </div>
            <div class="panel-body tight">
              ${
                data.heatmap?.length
                  ? '<div class="chart" data-heatmap style="height:460px"></div>'
                  : ui.emptyState('暂无热力图数据', '全市场快照暂不可用，稍后刷新页面。')
              }
            </div>
          </section>

          <section class="panel">
            <div class="panel-head">
              <div class="panel-title">主要指数走势 <span class="sub">近 ${sparkLength || 60} 个交易日 · 归一化 = 100</span></div>
            </div>
            <div class="panel-body tight">
              ${
                sparkLength
                  ? '<div class="chart" data-index-chart style="height:268px"></div>'
                  : ui.emptyState('暂无指数走势', '指数分时与历史数据暂不可用。')
              }
            </div>
          </section>

          <section class="panel watchlist-panel">
            <div class="panel-head">
              <div class="panel-title">自选股 <span class="sub">保存在本地浏览器</span></div>
              <div class="panel-actions">
                <form class="watch-add" data-watch-form>
                  <input name="symbol" type="text" placeholder="添加代码" maxlength="12" autocomplete="off" spellcheck="false" aria-label="添加自选代码">
                  <button type="submit" title="添加自选">${ui.icon('plus', 13)}</button>
                </form>
              </div>
            </div>
            <div class="watch-grid" data-watch-grid>${ui.loadingInline('加载自选行情')}</div>
          </section>
        </div>

        <div class="col-stack col-side">
          <section class="panel">
            <div class="panel-head">
              <div class="panel-title">异动榜 <span class="sub">市值 ≥ 10 亿美元</span></div>
              <div class="tab-bar" data-movers-tabs>
                <button type="button" class="active" data-kind="gainers">涨幅</button>
                <button type="button" data-kind="losers">跌幅</button>
                <button type="button" data-kind="active">成交额</button>
              </div>
            </div>
            <div class="panel-body flush">
              <div class="mover-list" data-movers>${moverRows(data.movers?.gainers, 'gainers')}</div>
            </div>
          </section>

          <section class="panel">
            <div class="panel-head">
              <div class="panel-title">市场宽度 <span class="sub">普通股涨跌分布</span></div>
            </div>
            <div class="panel-body">${breadthBlock(data)}</div>
          </section>

          <section class="panel">
            <div class="panel-head">
              <div class="panel-title">宏观快照 <span class="sub">FRED</span></div>
              <div class="panel-actions"><a class="btn small ghost" href="#/macro">宏观雷达</a></div>
            </div>
            <div class="panel-body">${macroMini(data.macro)}</div>
          </section>
        </div>
      </div>

      <div class="overview-lower-grid">
        <section class="panel overview-sectors">
          <div class="panel-head">
            <div class="panel-title">板块表现 <span class="sub">SPDR 行业 ETF</span></div>
            <div class="panel-actions"><a class="btn small ghost" href="#/screener">选股器</a></div>
          </div>
          <div class="panel-body">${sectorRows(data.sectors)}</div>
        </section>

        <section class="panel overview-earnings">
          <div class="panel-head">
            <div class="panel-title">财报日历 <span class="sub">未来 7 天 · 按市值排序</span></div>
            <div class="panel-actions"><span class="badge">${fmtInt((data.earnings || []).length)} 条</span></div>
          </div>
          <div class="panel-body">${earningsRows(data.earnings)}</div>
        </section>
      </div>

      <section class="panel section-gap">
        <div class="panel-head">
          <div class="panel-title">市场快讯 <span class="sub">东方财富 7×24</span></div>
          <div class="panel-actions"><span class="badge">实时滚动</span></div>
        </div>
        <div class="panel-body">${newsList(data.news, { limit: 10 })}</div>
      </section>
    </section>`;

  const heatmapEl = $('[data-heatmap]', root);
  if (heatmapEl) {
    charts.treemap(heatmapEl, data.heatmap, { onSelect: (symbol) => navigate(symbol) });
  }
  const trendEl = $('[data-index-chart]', root);
  if (trendEl) charts.normalizedIndexChart(trendEl, data.sparklines);

  $$('[data-spark]', root).forEach((el) => {
    const symbol = el.dataset.spark;
    const index = (data.indices || []).find((item) => item.symbol === symbol);
    const values = data.sparklines?.[symbol];
    if (Array.isArray(values) && values.length > 2) {
      charts.sparkline(el, values, Number(index?.change_pct) >= 0);
    }
  });

  const breadthEl = $('[data-breadth]', root);
  if (breadthEl) charts.breadthGauge(breadthEl, data.breadth?.up_ratio);

  let watchToken = 0;

  async function loadWatch() {
    const grid = $('[data-watch-grid]', root);
    if (!grid) return;
    const symbols = store.watchlist();
    const token = ++watchToken;
    if (!symbols.length) {
      grid.innerHTML = ui.emptyState('自选列表为空', '在左侧自选面板或右上角输入股票代码，添加你关注的标的。');
      return;
    }
    grid.innerHTML = ui.loadingInline('加载自选行情');
    try {
      const payload = await api.get(`/api/quotes?symbols=${encodeURIComponent(symbols.join(','))}`, {
        signal,
        timeout: 45000,
      });
      if (!isActive() || token !== watchToken) return;
      const lookup = new Map((payload.items || []).map((item) => [item.symbol, item]));
      grid.innerHTML = symbols.map((symbol) => watchTile(lookup.get(symbol), symbol)).join('');
    } catch (error) {
      if (error?.name === 'AbortError' || token !== watchToken) return;
      grid.innerHTML = ui.errorPanel(error.message || '自选行情加载失败');
      ui.bindRetry(grid, loadWatch);
    }
  }

  const watchForm = $('[data-watch-form]', root);
  watchForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const input = watchForm.querySelector('input[name="symbol"]');
    const code = String(input?.value || '').trim().toUpperCase();
    if (!/^[A-Z0-9.\-]{1,12}$/.test(code)) {
      ui.toast('请输入有效的美股代码，例如 NVDA', 'warn');
      return;
    }
    if (store.isWatched(code)) {
      ui.toast(`${code} 已在自选列表中`, 'info');
      return;
    }
    try {
      const payload = await api.get(`/api/quotes?symbols=${encodeURIComponent(code)}`, {
        signal,
        timeout: 30000,
      });
      if (!payload.items?.length) {
        ui.toast(`未找到代码 ${code} 的行情`, 'error');
        return;
      }
      store.addWatch(code);
      if (input) input.value = '';
      ui.toast(`已添加 ${code} 到自选`, 'success');
    } catch (error) {
      if (error?.name === 'AbortError') return;
      ui.toast(error.message || '添加自选失败', 'error');
    }
  });

  $$('[data-movers-tabs] button', root).forEach((button) => {
    button.addEventListener('click', () => {
      $$('[data-movers-tabs] button', root).forEach((item) => item.classList.toggle('active', item === button));
      const kind = button.dataset.kind;
      const list = $('[data-movers]', root);
      if (list) list.innerHTML = moverRows(data.movers?.[kind], kind);
    });
  });

  root.addEventListener('click', (event) => {
    const remove = event.target.closest('[data-remove]');
    if (remove) {
      event.stopPropagation();
      const symbol = remove.dataset.remove;
      store.removeWatch(symbol);
      ui.toast(`已移出 ${symbol}`, 'info', 1800);
      return;
    }
    const macro = event.target.closest('[data-macro]');
    if (macro) {
      navigate(`#/macro?series=${encodeURIComponent(macro.dataset.macro)}`);
      return;
    }
    if (event.target.closest('button, a, input, select, form')) return;
    const target = event.target.closest('[data-symbol]');
    if (target?.dataset.symbol) navigate(target.dataset.symbol);
  });

  const onWatchStore = (event) => {
    if (event.detail?.type === 'watchlist') loadWatch();
  };
  window.addEventListener('starmap:store', onWatchStore);

  loadWatch();
  return () => window.removeEventListener('starmap:store', onWatchStore);
}
