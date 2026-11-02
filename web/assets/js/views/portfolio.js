import { api } from '../api.js';
import { store } from '../store.js';
import * as ui from '../ui.js';
import * as charts from '../charts.js';
import { $, $$, esc, fmtDate, fmtNum, fmtPct, tone } from '../utils.js';
import { asOfBadge, viewHead } from './common.js';

export const meta = {
  title: '组合回测',
  eyebrow: 'PORTFOLIO LAB',
};

const RANGES = ['1Y', '3Y', '5Y'];
const BENCHMARKS = ['SPY', 'QQQ', 'IWM', 'DIA'];
const REBALANCE = [
  ['buy_hold', '买入持有'],
  ['monthly', '月度'],
  ['quarterly', '季度'],
  ['annual', '年度'],
];
const REBALANCE_LABEL = Object.fromEntries(REBALANCE);

function validSymbol(value) {
  return /^[A-Z][A-Z0-9.\-]{0,15}$/.test(String(value || '').trim().toUpperCase());
}

function normalizedHoldings(holdings) {
  const clean = (holdings || [])
    .map((item) => ({ symbol: String(item.symbol || '').toUpperCase(), weight: Number(item.weight) }))
    .filter((item) => validSymbol(item.symbol) && Number.isFinite(item.weight) && item.weight > 0);
  const total = clean.reduce((sum, item) => sum + item.weight, 0);
  return clean.map((item) => ({ ...item, normalized: total ? item.weight / total * 100 : 0 }));
}

function weightTotal(holdings) {
  return (holdings || []).reduce((sum, item) => sum + (Number(item.weight) || 0), 0);
}

function fmtPp(value, digits = 1) {
  if (!Number.isFinite(Number(value))) return '—';
  const number = Number(value);
  return `${number > 0 ? '+' : ''}${fmtNum(number, digits)}pp`;
}

function riskGapTone(value) {
  if (!Number.isFinite(Number(value))) return 'flat';
  return Number(value) > 2 ? 'warn' : Number(value) < -2 ? 'cool' : 'flat';
}

function emptyResults() {
  return `<section class="panel">${ui.emptyState(
    '从一个组合假设开始',
    '选择股票、设置目标权重，保存组合并运行历史回测。回测不含交易成本与税务。',
    `<button type="button" class="btn small" data-pf-sample-inline>${ui.icon('play', 13)}载入示例组合</button>`,
  )}</section>`;
}

function allocRows(items) {
  if (!items?.length) return '<li class="pf-alloc-empty">暂无配置数据</li>';
  const total = items.reduce((sum, item) => sum + (Number(item.weight) || 0), 0) || 1;
  const colors = charts.palette();
  return items.map((item, index) => `
    <li class="pf-alloc-row">
      <span class="pf-alloc-dot" style="background:${colors[index % colors.length]}"></span>
      <span class="pf-alloc-name" title="${esc(item.name)}">${esc(item.name)}</span>
      <span class="pf-alloc-bar"><i style="width:${Math.min(100, Number(item.weight) / total * 100)}%"></i></span>
      <b>${fmtNum(Number(item.weight), 1)}%</b>
    </li>`).join('');
}

export async function mount(root, params, ctx) {
  const { signal, isActive, navigate } = ctx;
  const draft = store.portfolioDraft();
  const querySymbols = String(params.symbols || '')
    .split(',')
    .map((item) => item.trim().toUpperCase())
    .filter(validSymbol);
  const uniqueQuery = Array.from(new Set(querySymbols)).slice(0, 20);
  const initialHoldings = uniqueQuery.length
    ? uniqueQuery.map((symbol) => ({ symbol, weight: Number((100 / uniqueQuery.length).toFixed(2)) }))
    : draft.holdings;
  const state = {
    id: uniqueQuery.length ? '' : draft.id,
    name: uniqueQuery.length ? '自选组合' : draft.name,
    holdings: initialHoldings,
    range: RANGES.includes(params.range) ? params.range : draft.range,
    benchmark: BENCHMARKS.includes(params.benchmark) ? params.benchmark : draft.benchmark,
    rebalance: REBALANCE.some(([key]) => key === (params.rebalance || draft.rebalance)) ? (params.rebalance || draft.rebalance) : 'quarterly',
    allocMode: 'holdings',
    diagnosticTab: 'risk',
    rollingMode: 'vol',
    payload: null,
    saved: store.savedPortfolios(),
    busy: false,
    dirty: false,
    disposed: false,
    token: 0,
    controller: null,
  };

  root.innerHTML = `
    <section class="view">
      ${viewHead({
        eyebrow: meta.eyebrow,
        title: '组合回测',
        sub: '选定股票与目标权重，保存研究组合，再用历史行情检验收益、回撤与再平衡。',
        actions: '<span data-pf-asof><span class="pill info">本地组合</span></span>',
      })}

      <section class="panel pf-builder">
        <div class="panel-head">
          <div class="panel-title">组合构建 <span class="sub">最多 20 只 · 目标权重自动归一</span></div>
          <div class="panel-actions">
            <button type="button" class="btn small ghost" data-pf-sample>${ui.icon('play', 13)}载入示例</button>
            <button type="button" class="btn small ghost" data-pf-new>新建</button>
          </div>
        </div>
        <div class="panel-body">
          <div class="pf-builder-grid">
            <div class="pf-holdings">
              <form class="pf-add-form" data-pf-add-form>
                <div class="pf-add-box">${ui.icon('search', 14)}<input type="text" maxlength="12" placeholder="输入股票代码，如 AAPL" autocomplete="off" spellcheck="false" data-pf-symbol-input aria-label="添加股票代码"></div>
                <button class="btn small" type="submit">${ui.icon('plus', 13)}添加股票</button>
              </form>
              <div class="pf-holdings-head"><span>标的</span><span>目标权重</span><span>归一后</span><span></span></div>
              <div class="pf-holding-list" data-pf-holdings></div>
              <div class="pf-weight-summary"><span data-pf-total>权重合计 0%</span><span data-pf-normalized-hint></span><button type="button" class="btn small ghost" data-pf-equal>等权</button></div>
            </div>
            <aside class="pf-config">
              <label class="pf-field"><span>组合名称</span><input class="input" type="text" maxlength="60" value="${esc(state.name)}" placeholder="例如 核心科技" data-pf-name></label>
              <div class="pf-config-group"><span>比较基准</span><div class="pf-options" data-pf-benchmark>${BENCHMARKS.map((value) => `<button type="button" data-value="${value}" class="${value === state.benchmark ? 'active' : ''}">${value}</button>`).join('')}</div></div>
              <div class="pf-config-group"><span>回测区间</span><div class="pf-options" data-pf-range>${RANGES.map((value) => `<button type="button" data-value="${value}" class="${value === state.range ? 'active' : ''}">${value}</button>`).join('')}</div></div>
              <div class="pf-config-group"><span>再平衡</span><div class="pf-options pf-rebalance-options" data-pf-rebalance>${REBALANCE.map(([value, label]) => `<button type="button" data-value="${value}" class="${value === state.rebalance ? 'active' : ''}">${label}</button>`).join('')}</div></div>
              <div class="pf-config-actions">
                <button type="button" class="btn small ghost" data-pf-save>${ui.icon('file', 13)}保存组合</button>
                <button type="button" class="btn primary" data-pf-run>${ui.icon('activity', 14)}运行回测</button>
              </div>
              <p class="pf-config-note">历史模拟，不含佣金、滑点与税费；目标权重和再平衡规则会保存到本机。</p>
            </aside>
          </div>
          <div class="pf-saved-block">
            <div class="pf-saved-head"><span>已保存组合 <b data-pf-saved-count>0</b></span><small>点击载入并重算</small></div>
            <div class="pf-saved-list" data-pf-saved></div>
          </div>
        </div>
      </section>

      <div data-pf-results>${state.holdings.length ? `<section class="panel">${ui.loadingInline('准备回测…')}</section>` : emptyResults()}</div>
    </section>`;

  const results = $('[data-pf-results]', root);
  const holdingList = $('[data-pf-holdings]', root);
  const nameInput = $('[data-pf-name]', root);
  const runButton = $('[data-pf-run]', root);
  const savedList = $('[data-pf-saved]', root);
  let persistTimer = null;

  function snapshot() {
    return {
      id: state.id,
      name: String(state.name || '').trim(),
      holdings: state.holdings,
      range: state.range,
      benchmark: state.benchmark,
      rebalance: state.rebalance,
    };
  }

  function persist() {
    store.setPortfolioDraft(snapshot());
  }

  function schedulePersist() {
    clearTimeout(persistTimer);
    persistTimer = setTimeout(persist, 250);
  }

  function setAsOf(payload) {
    const holder = $('[data-pf-asof]', root);
    if (!holder) return;
    if (!payload || payload.empty) {
      holder.innerHTML = '<span class="pill info">研究组合</span>';
      return;
    }
    const summary = payload.summary || {};
    holder.innerHTML = `${asOfBadge(payload.as_of)}<span class="pill info">${summary.holdings_count || state.holdings.length} 只 · ${esc(REBALANCE_LABEL[payload.rebalance] || '')}</span>`;
  }

  function paintRunButton() {
    const hasHoldings = normalizedHoldings(state.holdings).length > 0;
    runButton.disabled = state.busy || !hasHoldings;
    if (state.busy) {
      runButton.innerHTML = `<span class="spinner" style="width:12px;height:12px;border-width:1.5px"></span>回测中…`;
      return;
    }
    const label = state.dirty && state.payload ? '更新结果' : state.payload ? '重新回测' : '运行回测';
    runButton.innerHTML = `${ui.icon(state.dirty ? 'refresh' : 'activity', 14)}${label}`;
  }

  function markDirty() {
    if (state.payload) {
      state.dirty = true;
      const banner = $('[data-pf-stale]', results);
      if (banner) banner.hidden = false;
    }
    paintRunButton();
  }

  function setBusy(busy) {
    state.busy = busy;
    $$('button:not([data-pf-delete]), input', $('.pf-builder', root)).forEach((element) => {
      if (element === nameInput) return;
      element.disabled = busy;
    });
    paintRunButton();
  }

  function renderHoldings() {
    if (!state.holdings.length) {
      holdingList.innerHTML = `<div class="pf-empty-holdings"><span>组合还是空的</span><small>输入代码添加第一只股票，或载入示例组合。</small></div>`;
    } else {
      const normalized = normalizedHoldings(state.holdings);
      holdingList.innerHTML = state.holdings.map((item, index) => `
        <div class="pf-holding-row" data-pf-index="${index}">
          <div class="pf-holding-symbol"><span>${esc(item.symbol)}</span><small>${index === 0 ? '主标的' : '成分'}</small></div>
          <label class="pf-weight-input"><input type="number" min="0.01" max="10000" step="0.1" value="${esc(String(item.weight))}" data-pf-weight="${index}" aria-label="${esc(item.symbol)} 目标权重"><span>%</span></label>
          <span class="pf-normalized">${fmtNum(normalized[index]?.normalized, 1)}%</span>
          <button type="button" class="pf-remove" data-pf-remove="${index}" title="移除 ${esc(item.symbol)}" aria-label="移除 ${esc(item.symbol)}">${ui.icon('x', 12)}</button>
        </div>`).join('');
    }
    const total = weightTotal(state.holdings);
    const hint = $('[data-pf-normalized-hint]', root);
    $('[data-pf-total]', root).textContent = `权重合计 ${fmtNum(total, 1)}%`;
    if (hint) hint.textContent = state.holdings.length ? (Math.abs(total - 100) < 0.01 ? '已归一' : '回测按 100% 归一') : '';
    paintRunButton();
  }

  function updateWeightPreview() {
    const normalized = normalizedHoldings(state.holdings);
    $$('[data-pf-index]', holdingList).forEach((row) => {
      const index = Number(row.dataset.pfIndex);
      const cell = $('.pf-normalized', row);
      if (cell) cell.textContent = `${fmtNum(normalized.find((item) => item.symbol === state.holdings[index]?.symbol)?.normalized, 1)}%`;
    });
    const total = weightTotal(state.holdings);
    $('[data-pf-total]', root).textContent = `权重合计 ${fmtNum(total, 1)}%`;
    const hint = $('[data-pf-normalized-hint]', root);
    if (hint) hint.textContent = state.holdings.length ? (Math.abs(total - 100) < 0.01 ? '已归一' : '回测按 100% 归一') : '';
    paintRunButton();
  }

  function renderSaved() {
    state.saved = store.savedPortfolios();
    $('[data-pf-saved-count]', root).textContent = String(state.saved.length);
    if (!state.saved.length) {
      savedList.innerHTML = '<p class="pf-saved-empty">还没有保存的组合。设置名称后点击“保存组合”，可以保留多组研究方案。</p>';
      return;
    }
    savedList.innerHTML = state.saved.map((profile) => `
      <article class="pf-saved-card ${profile.id === state.id ? 'active' : ''}">
        <button type="button" class="pf-saved-load" data-pf-load="${esc(profile.id)}">
          <span>${esc(profile.name)}</span>
          <small>${profile.holdings.length} 只 · ${esc(profile.range)} · ${esc(REBALANCE_LABEL[profile.rebalance] || profile.rebalance)} · ${esc(profile.benchmark)}</small>
        </button>
        <button type="button" class="pf-saved-delete" data-pf-delete="${esc(profile.id)}" title="删除组合" aria-label="删除 ${esc(profile.name)}">${ui.icon('trash', 12)}</button>
      </article>`).join('');
  }

  function paintConfig() {
    $$('[data-pf-benchmark] button', root).forEach((button) => button.classList.toggle('active', button.dataset.value === state.benchmark));
    $$('[data-pf-range] button', root).forEach((button) => button.classList.toggle('active', button.dataset.value === state.range));
    $$('[data-pf-rebalance] button', root).forEach((button) => button.classList.toggle('active', button.dataset.value === state.rebalance));
    nameInput.value = state.name;
  }

  function repaintBuilder() {
    renderHoldings();
    paintConfig();
    renderSaved();
    setBusy(state.busy);
  }

  function addSymbol(raw) {
    const symbol = String(raw || '').trim().toUpperCase();
    if (!validSymbol(symbol)) {
      ui.toast('请输入有效的美股代码', 'warn');
      return;
    }
    if (state.holdings.some((item) => item.symbol === symbol)) {
      ui.toast(`${symbol} 已在组合中`, 'info');
      return;
    }
    if (state.holdings.length >= 20) {
      ui.toast('组合最多 20 只', 'warn');
      return;
    }
    state.holdings.push({ symbol, weight: state.holdings.length ? 10 : 100 });
    $('[data-pf-symbol-input]', root).value = '';
    renderHoldings();
    schedulePersist();
    markDirty();
  }

  function equalize() {
    if (!state.holdings.length) return;
    const weight = Number((100 / state.holdings.length).toFixed(2));
    state.holdings = state.holdings.map((item) => ({ ...item, weight }));
    renderHoldings();
    schedulePersist();
    markDirty();
  }

  function saveCurrent() {
    const clean = normalizedHoldings(state.holdings);
    if (!clean.length) {
      ui.toast('请先添加至少一只股票', 'warn');
      return;
    }
    if (!String(state.name || '').trim()) {
      ui.toast('请为组合填写名称', 'warn');
      nameInput.focus();
      return;
    }
    const entry = store.savePortfolio(snapshot());
    state.id = entry.id;
    state.name = entry.name;
    persist();
    renderSaved();
    ui.toast(`已保存「${entry.name}」`, 'success', 1600);
  }

  function loadSaved(id) {
    const profile = store.savedPortfolios().find((item) => item.id === id);
    if (!profile) return;
    state.id = profile.id;
    state.name = profile.name;
    state.holdings = profile.holdings.map((item) => ({ ...item }));
    state.range = profile.range;
    state.benchmark = profile.benchmark;
    state.rebalance = profile.rebalance;
    persist();
    repaintBuilder();
    runBacktest({ focusResults: true });
  }

  function loadSample() {
    state.holdings = store.sampleHoldings();
    state.name = state.name || '核心科技示例';
    state.range = '5Y';
    state.rebalance = 'quarterly';
    state.benchmark = 'SPY';
    state.id = '';
    persist();
    repaintBuilder();
    runBacktest({ focusResults: true });
  }

  function drawAllocation(payload) {
    const holder = $('[data-pf-allocation]', results);
    if (!holder) return;
    const items = (payload.allocation?.[state.allocMode] || []).filter((item) => Number(item.weight) > 0);
    holder.innerHTML = `
      <div class="pf-alloc-visual">
        <div class="chart pf-alloc-chart" data-pf-donut></div>
        <div class="pf-alloc-center"><span>目标配置</span><strong>100%</strong></div>
      </div>
      <ul class="pf-alloc-list">${allocRows(items)}</ul>`;
    if (items.length) charts.donut($('[data-pf-donut]', holder), items.map((item) => ({ name: item.name, value: item.weight })));
    $$('[data-pf-alloc-mode] button', results).forEach((button) => button.classList.toggle('active', button.dataset.alloc === state.allocMode));
  }

  function diagnosticTile(label, value, sub) {
    return `<div class="pf-diag-tile"><span>${esc(label)}</span><strong>${value}</strong><small>${sub}</small></div>`;
  }

  function riskRows(payload) {
    return (payload.holdings || [])
      .filter((item) => Number.isFinite(Number(item.risk_contribution)))
      .slice()
      .sort((a, b) => Number(b.risk_contribution) - Number(a.risk_contribution));
  }

  function correlationSubset(payload) {
    const corr = payload.risk?.correlation || {};
    const allSymbols = corr.symbols || [];
    const matrix = corr.matrix || [];
    if (allSymbols.length < 2 || matrix.length !== allSymbols.length) return null;
    const chosen = (payload.holdings || [])
      .slice()
      .sort((a, b) => Number(b.weight) - Number(a.weight))
      .slice(0, 8)
      .map((item) => item.symbol)
      .filter((symbol) => allSymbols.includes(symbol));
    if (chosen.length < 2) return null;
    const indices = chosen.map((symbol) => allSymbols.indexOf(symbol));
    return {
      symbols: chosen,
      matrix: indices.map((row) => indices.map((column) => matrix[row]?.[column])),
    };
  }

  function renderRiskTab(payload) {
    const risk = payload.risk || {};
    const concentration = risk.concentration || {};
    const diversification = risk.diversification || {};
    const rows = riskRows(payload);
    const top = rows[0];
    const topThree = rows.slice(0, 3);
    const topThreeRisk = topThree.reduce((sum, item) => sum + (Number(item.risk_contribution) || 0), 0);
    const topThreeWeight = topThree.reduce((sum, item) => sum + (Number(item.weight) || 0), 0);
    const shown = rows.slice(0, 8);
    const omitted = rows.slice(8);
    const omittedRisk = omitted.reduce((sum, item) => sum + (Number(item.risk_contribution) || 0), 0);
    const corr = correlationSubset(payload);
    const rolling = risk.rolling || {};
    const betaAvailable = (rolling.beta || []).some((value) => Number.isFinite(Number(value)));
    const exposureGap = topThreeRisk - topThreeWeight;
    const effectiveText = concentration.effective_holdings === null || concentration.effective_holdings === undefined
      ? '—'
      : `${fmtNum(concentration.effective_holdings, 1)} 只`;
    const riskBetsText = diversification.effective_risk_bets === null || diversification.effective_risk_bets === undefined
      ? '—'
      : `${fmtNum(diversification.effective_risk_bets, 1)} 个`;
    const narrative = topThree.length
      ? `风险贡献前三为 ${topThree.map((item) => item.symbol).join('、')}，合计 ${fmtPct(topThreeRisk, 1, false)}，对应目标权重 ${fmtPct(topThreeWeight, 1, false)}。${exposureGap > 5 ? '风险集中度高于资金权重，组合对少数标的的波动更敏感。' : '风险来源与目标权重基本匹配。'}`
      : '风险分解数据不足，需延长共同行情区间。';
    return `
      <div class="pf-diag-tiles">
        ${diagnosticTile('有效持仓', effectiveText, `HHI ${fmtNum(concentration.hhi, 3)} · 前三大 ${fmtPct(concentration.top3_weight, 1, false)}`)}
        ${diagnosticTile('分散化比率', fmtNum(diversification.ratio, 2), `加权个股波动 ${fmtPct(diversification.weighted_volatility, 1, false)} / 组合 ${fmtPct(diversification.portfolio_volatility, 1, false)}`)}
        ${diagnosticTile('有效风险来源', riskBetsText, `风险 HHI ${fmtNum(diversification.risk_hhi, 3)}`)}
        ${diagnosticTile('最大风险贡献', top ? esc(top.symbol) : '—', top ? `风险 ${fmtPct(top.risk_contribution, 1, false)} · 权重 ${fmtPct(top.weight, 1, false)}` : '—')}
      </div>
      <div class="pf-diag-grid">
        <section class="pf-diag-block">
          <header><strong>风险贡献</strong><span>目标权重 · 全区间协方差</span></header>
          <div class="pf-risk-legend"><span><i class="risk"></i>风险贡献</span><span><i class="weight"></i>目标权重</span></div>
          <div class="pf-risk-scale" aria-hidden="true"><span>0%</span><span>50%</span><span>100%</span></div>
          <div class="pf-risk-list">
            ${shown.map((item) => {
              const riskValue = Number(item.risk_contribution) || 0;
              const weightValue = Number(item.weight) || 0;
              return `<div class="pf-risk-row">
                <div class="pf-risk-row-head"><b>${esc(item.symbol)}</b><span>风险 ${fmtPct(riskValue, 1, false)}</span><span>权重 ${fmtPct(weightValue, 1, false)}</span></div>
                <div class="pf-risk-track"><i style="width:${Math.max(0, Math.min(100, riskValue))}%"></i><u style="left:${Math.max(0, Math.min(100, weightValue))}%"></u></div>
              </div>`;
            }).join('') || '<p class="field-hint">暂无风险贡献数据。</p>'}
          </div>
          ${omitted.length ? `<p class="pf-diag-note">其余 ${omitted.length} 只合计风险贡献 ${fmtPct(omittedRisk, 1, false)}。</p>` : ''}
          <p class="pf-diag-note">${esc(narrative)}</p>
          <p class="pf-diag-note">风险贡献按目标权重与全区间日收益协方差计算，属于事后分解，不是未来风险预测。</p>
        </section>
        <section class="pf-diag-block">
          <header><strong>持仓相关性</strong><span>${corr ? `前 ${corr.symbols.length} 大权重 · 日收益` : '至少需要两只持仓'}</span></header>
          ${corr ? `<div class="chart pf-corr-chart" data-pf-corr style="height:${Math.max(244, Math.min(340, 80 + corr.symbols.length * 30))}px"></div>` : '<p class="field-hint">持仓不足两只，暂无相关性矩阵。</p>'}
          <p class="pf-diag-note">相关系数越接近 1，走势越同步；较低或为负的相关系数通常有助于降低组合波动。</p>
        </section>
      </div>
      <section class="pf-diag-block pf-rolling-block">
        <header>
          <div><strong>滚动风险</strong><span>${rolling.window || 60} 个交易日窗口</span></div>
          ${betaAvailable ? `<div class="seg pf-rolling-tabs" data-pf-rolling-mode role="group" aria-label="滚动风险口径">
            <button type="button" data-rolling-mode="vol" class="${state.rollingMode !== 'beta' ? 'active' : ''}">波动率</button>
            <button type="button" data-rolling-mode="beta" class="${state.rollingMode === 'beta' ? 'active' : ''}">Beta</button>
          </div>` : ''}
        </header>
        ${rolling.dates?.length ? '<div class="chart" data-pf-rolling style="height:224px"></div>' : '<p class="field-hint">行情区间不足 70 个交易日，无法计算滚动风险。</p>'}
        <p class="pf-diag-note">滚动窗口只用于观察风险状态的阶段性变化，不代表未来波动预测；Beta 以基准 = 1 为参照。</p>
      </section>`;
  }

  function renderDrawdownTab(payload) {
    const metrics = payload.metrics || {};
    const risk = payload.risk || {};
    const episodes = risk.drawdown_episodes || [];
    const stress = risk.stress_windows || [];
    const current = payload.drawdown?.portfolio?.length ? payload.drawdown.portfolio[payload.drawdown.portfolio.length - 1] : null;
    const deepest = episodes[0];
    const worst20 = stress.find((item) => item.window === 20);
    return `
      <div class="pf-diag-tiles">
        ${diagnosticTile('最大回撤', fmtPct(metrics.max_drawdown), '峰值至谷底')}
        ${diagnosticTile('当前回撤', fmtPct(current), current !== null && Number(current) > -0.01 ? '接近历史高位' : '距最近峰值')}
        ${diagnosticTile('最深下跌', deepest ? `${fmtNum(deepest.decline_sessions, 0)} 交易日` : '—', deepest ? `${esc(deepest.peak_date)} → ${esc(deepest.trough_date)}` : '—')}
        ${diagnosticTile('最差 20 日', worst20 ? fmtPct(worst20.portfolio_return) : '—', worst20 ? `${esc(worst20.start)} → ${esc(worst20.end)}` : '—')}
      </div>
      <div class="pf-diag-grid">
        <section class="pf-diag-block">
          <header><strong>主要回撤阶段</strong><span>按深度排序 · 最多 3 段</span></header>
          ${episodes.length ? `<div class="pf-episode-list">${episodes.map((item, index) => `
            <div class="pf-episode">
              <div class="pf-episode-top"><span>回撤 ${index + 1}</span><b class="neg">${fmtPct(item.depth_pct)}</b></div>
              <div class="pf-episode-dates">${esc(item.peak_date)} <i>→</i> ${esc(item.trough_date)} <i>→</i> ${item.recovery_date ? esc(item.recovery_date) : '尚未修复'}</div>
              <div class="pf-episode-meta"><span>下跌 ${fmtNum(item.decline_sessions, 0)} 交易日</span><span>${item.recovered ? `修复 ${fmtNum(item.recovery_sessions, 0)} 交易日` : '仍未回到前高'}</span></div>
            </div>`).join('')}</div>` : '<p class="field-hint">区间内没有形成可识别的回撤阶段。</p>'}
        </section>
        <section class="pf-diag-block">
          <header><strong>历史压力窗口</strong><span>滚动实际收益最差区间</span></header>
          ${stress.length ? `<div class="pf-stress-list">${stress.map((item) => `
            <div class="pf-stress-row">
              <div class="pf-stress-main"><b>${esc(item.label)}</b><span>${esc(item.start)} → ${esc(item.end)}</span></div>
              <div class="pf-stress-value"><strong class="neg">${fmtPct(item.portfolio_return)}</strong><small>组合</small></div>
              <div class="pf-stress-value"><strong>${fmtPct(item.benchmark_return)}</strong><small>${esc(payload.benchmark || '基准')}</small></div>
            </div>`).join('')}</div>` : '<p class="field-hint">共同行情不足，无法计算压力窗口。</p>'}
          <p class="pf-diag-note">压力窗口来自实际历史中最差的 20 / 60 个交易日复合收益，不是假设情景或未来预测。</p>
        </section>
      </div>`;
  }

  function renderContributionTab(payload) {
    const metrics = payload.metrics || {};
    const holdings = (payload.holdings || [])
      .filter((item) => Number.isFinite(Number(item.return_contribution)))
      .slice()
      .sort((a, b) => Number(b.return_contribution) - Number(a.return_contribution));
    const best = holdings[0];
    const worst = holdings[holdings.length - 1];
    const maxAbs = Math.max(1, ...holdings.map((item) => Math.abs(Number(item.return_contribution) || 0)));
    const over = (payload.holdings || [])
      .filter((item) => Number.isFinite(Number(item.risk_contribution)) && Number.isFinite(Number(item.weight)))
      .slice()
      .sort((a, b) => Number(b.risk_contribution) - Number(b.weight) - (Number(a.risk_contribution) - Number(a.weight)))[0];
    return `
      <div class="pf-diag-tiles">
        ${diagnosticTile('区间收益贡献', fmtPct(metrics.total_return), '各标的盈亏合计')}
        ${diagnosticTile('最佳贡献', best ? esc(best.symbol) : '—', best ? fmtPp(best.return_contribution) : '—')}
        ${diagnosticTile(worst && Number(worst.return_contribution) < 0 ? '最大拖累' : '最低贡献', worst ? esc(worst.symbol) : '—', worst ? fmtPp(worst.return_contribution) : '—')}
        ${diagnosticTile('风险超配最大', over ? esc(over.symbol) : '—', over ? fmtPp(Number(over.risk_contribution) - Number(over.weight)) : '—')}
      </div>
      <section class="pf-diag-block">
        <header><strong>收益贡献</strong><span>持仓盈亏 / 初始本金 · 累计百分点</span></header>
        <div class="pf-contrib-list">
          ${holdings.map((item) => {
            const value = Number(item.return_contribution) || 0;
            const width = Math.abs(value) / maxAbs * 50;
            const style = value >= 0 ? `left:50%;width:${width}%` : `left:${50 - width}%;width:${width}%`;
            return `<div class="pf-contrib-row">
              <b>${esc(item.symbol)}</b>
              <div class="pf-contrib-track"><span></span><i class="${value >= 0 ? 'pos' : 'neg'}" style="${style}"></i></div>
              <em class="${value >= 0 ? 'pos' : 'neg'}">${fmtPp(value)}</em>
            </div>`;
          }).join('') || '<p class="field-hint">暂无收益贡献数据。</p>'}
        </div>
        ${holdings.length ? `<div class="pf-contrib-scale" aria-hidden="true"><span></span><div><span>${fmtPp(-maxAbs)}</span><span>0</span><span>${fmtPp(maxAbs)}</span></div><span></span></div>` : ''}
      </section>
      <section class="pf-diag-block pf-contrib-table-block">
        <header><strong>收益与风险归属</strong><span>目标权重与平均持仓权重</span></header>
        <div class="table-wrap">
          <table class="data-table pf-contrib-table">
            <thead><tr><th>标的</th><th>目标权重</th><th>平均权重</th><th>收益贡献</th><th>风险占比</th><th>风险预算差</th></tr></thead>
            <tbody>${holdings.map((item) => {
              const contribution = Number(item.return_contribution);
              const hasRisk = Number.isFinite(Number(item.risk_contribution));
              const riskContribution = hasRisk ? Number(item.risk_contribution) : null;
              const gap = hasRisk ? riskContribution - Number(item.weight) : null;
              return `<tr><td><div class="sym-cell"><div><div class="sym">${esc(item.symbol)}</div><div class="nm">${esc(item.name || '')}</div></div></div></td>
                <td class="num-cell">${fmtNum(item.weight, 1)}%</td>
                <td class="num-cell">${fmtNum(item.average_weight, 1)}%</td>
                <td class="num-cell ${tone(contribution)}">${fmtPp(contribution)}</td>
                <td class="num-cell">${hasRisk ? `${fmtNum(riskContribution, 1)}%` : '—'}</td>
                <td class="num-cell ${riskGapTone(gap)}">${hasRisk ? fmtPp(gap) : '—'}</td></tr>`;
            }).join('')}</tbody>
          </table>
        </div>
        <p class="pf-diag-note">收益贡献按各标的日持仓盈亏累计并除以初始本金，合计等于组合区间收益；再平衡只转移本金，不改变盈亏归属。风险预算差 = 风险占比 − 目标权重。</p>
      </section>`;
  }

  function drawRollingChart(payload) {
    const el = $('[data-pf-rolling]', results);
    const rolling = payload?.risk?.rolling;
    if (!el || !rolling?.dates?.length) return;
    charts.rollingRiskChart(el, {
      dates: rolling.dates,
      portfolioVol: rolling.portfolio_vol || [],
      benchmarkVol: rolling.benchmark_vol || [],
      beta: rolling.beta || [],
      mode: state.rollingMode,
      labels: {
        portfolio: '组合波动',
        benchmark: `${payload.benchmark || '基准'} 波动`,
        beta: '组合 Beta',
      },
    });
  }

  function paintDiagnostic() {
    const body = $('[data-pf-diagnostic-body]', results);
    if (!body || !state.payload) return;
    charts.clear($('[data-pf-corr]', body));
    charts.clear($('[data-pf-rolling]', body));
    $$('[data-pf-diagnostic-tabs] button', results).forEach((button) => {
      const active = button.dataset.diagnosticTab === state.diagnosticTab;
      button.classList.toggle('active', active);
      button.setAttribute('aria-selected', String(active));
    });
    const tab = state.diagnosticTab;
    body.innerHTML = tab === 'drawdown'
      ? renderDrawdownTab(state.payload)
      : tab === 'contribution'
        ? renderContributionTab(state.payload)
        : renderRiskTab(state.payload);
    if (tab !== 'risk') return;
    requestAnimationFrame(() => {
      if (!state.payload || state.diagnosticTab !== 'risk' || !body.isConnected) return;
      const corr = correlationSubset(state.payload);
      const corrEl = $('[data-pf-corr]', body);
      if (corr && corrEl) charts.correlationHeatmap(corrEl, { symbols: corr.symbols, matrix: corr.matrix });
      drawRollingChart(state.payload);
    });
  }

  function renderResults(payload) {
    state.payload = payload;
    state.dirty = false;
    if (!(payload.risk?.rolling?.beta || []).some((value) => Number.isFinite(Number(value)))) {
      state.rollingMode = 'vol';
    }
    charts.disposeAll();
    const metrics = payload.metrics || {};
    const perf = payload.performance || {};
    const dd = payload.drawdown || {};
    const summary = payload.summary || {};
    const holdings = payload.holdings || [];
    const annual = payload.annual_returns || [];
    const benchmarkLast = perf.benchmark?.length ? perf.benchmark[perf.benchmark.length - 1] : null;
    const excess = benchmarkLast !== null && metrics.total_return !== null ? metrics.total_return - (benchmarkLast - 100) : null;
    const cards = [
      ['区间收益', fmtPct(metrics.total_return), `${esc(summary.start || '—')} → ${esc(summary.end || '—')}`, tone(metrics.total_return)],
      ['年化收益 CAGR', fmtPct(metrics.annual_return), `共同交易日 ${summary.common_days ?? '—'} 天`, tone(metrics.annual_return)],
      ['最大回撤', fmtPct(metrics.max_drawdown), '峰值至谷底', 'neg'],
      ['年化波动', fmtPct(metrics.annualized_vol, 2, false), '日收益 · 252 日年化', ''],
      ['Sharpe', fmtNum(metrics.sharpe, 2), '无风险利率 4%', ''],
      ['相对基准', excess === null ? '—' : fmtPct(excess), `${payload.benchmark || '基准'} · 同区间`, tone(excess)],
    ];
    const riskTiles = [
      ['Sortino', fmtNum(metrics.sortino, 2)],
      ['Calmar', fmtNum(metrics.calmar, 2)],
      ['日 VaR 95%', fmtPct(metrics.var_95_daily, 2, false)],
      ['日 CVaR 95%', fmtPct(metrics.cvar_95_daily, 2, false)],
      ['Beta', fmtNum(metrics.beta, 2)],
      ['跟踪误差', fmtPct(metrics.tracking_error, 2, false)],
      ['信息比率', fmtNum(metrics.information_ratio, 2)],
      ['上行 / 下行捕获', `${fmtPct(metrics.upside_capture, 1, false)} / ${fmtPct(metrics.downside_capture, 1, false)}`],
    ];
    results.innerHTML = `
      ${(payload.warnings || []).length ? ui.warnBanner(payload.warnings) : ''}
      <div class="pf-stale-banner" data-pf-stale hidden>
        <span class="pf-stale-copy">${ui.icon('alert', 14)}<span>持仓或回测参数已变更，下方仍是上一次结果。</span></span>
        <small>${esc(summary.start || '—')} → ${esc(summary.end || '—')} · ${esc(payload.range || '')} · ${esc(REBALANCE_LABEL[payload.rebalance] || '')}</small>
        <button type="button" class="btn small ghost" data-pf-rerun>${ui.icon('refresh', 13)}更新结果</button>
      </div>
      <div class="summary-grid pf-summary-grid">
        ${cards.map(([label, value, sub, valueTone]) => `<div class="summary-card"><div class="label">${esc(label)}</div><div class="value ${valueTone || ''}">${value}</div><div class="sub">${sub}</div></div>`).join('')}
      </div>

      <div class="portfolio-charts">
        <section class="panel">
          <div class="panel-head"><div class="panel-title">组合净值 <span class="sub">起点 100 · ${esc(payload.benchmark || '')} 对照</span></div></div>
          <div class="chart-body">${perf.dates?.length ? '<div class="chart" data-pf-perf style="height:310px"></div>' : ui.emptyState('暂无走势数据', '共同历史不足。')}</div>
        </section>
        <section class="panel">
          <div class="panel-head"><div class="panel-title">目标配置</div><div class="panel-actions"><div class="seg" data-pf-alloc-mode><button type="button" data-alloc="holdings" class="${state.allocMode === 'holdings' ? 'active' : ''}">个股</button><button type="button" data-alloc="sectors" class="${state.allocMode === 'sectors' ? 'active' : ''}">行业</button></div></div></div>
          <div class="pf-allocation" data-pf-allocation></div>
        </section>
      </div>

      <div class="pf-secondary-grid">
        <section class="panel"><div class="panel-head"><div class="panel-title">回撤曲线 <span class="sub">历史高点到谷底</span></div></div><div class="chart-body">${dd.dates?.length ? '<div class="chart" data-pf-dd style="height:244px"></div>' : ui.emptyState('暂无回撤数据', '共同历史不足。')}</div></section>
        <section class="panel"><div class="panel-head"><div class="panel-title">年度收益 <span class="sub">自然年 · 组合 vs ${esc(payload.benchmark || '')}</span></div></div><div class="chart-body">${annual.length ? '<div class="chart" data-pf-annual style="height:244px"></div>' : ui.emptyState('暂无年度收益', '回测区间不足一个完整年度。')}</div></section>
      </div>

      <section class="panel section-gap">
        <div class="panel-head"><div class="panel-title">风险指标 <span class="sub">日收益口径 · 无风险利率 4%</span></div><div class="panel-actions"><span class="field-hint">${esc(summary.rebalance ? REBALANCE_LABEL[summary.rebalance] || summary.rebalance : '')}再平衡 · 未计费用</span></div></div>
        <div class="panel-body"><div class="risk-grid pf-risk-grid">${riskTiles.map(([label, value]) => `<div class="risk-tile"><div class="r-label">${esc(label)}</div><div class="r-value">${value}</div></div>`).join('')}</div></div>
      </section>

      <section class="panel section-gap pf-diagnostic-panel" data-pf-diagnostic-panel>
        <div class="panel-head">
          <div class="panel-title">组合诊断 <span class="sub">目标权重构建 · 全区间历史模拟</span></div>
          <div class="panel-actions"><div class="seg" data-pf-diagnostic-tabs role="tablist" aria-label="组合诊断视图">
            <button type="button" role="tab" data-diagnostic-tab="risk" aria-selected="${state.diagnosticTab === 'risk'}" class="${state.diagnosticTab === 'risk' ? 'active' : ''}">风险结构</button>
            <button type="button" role="tab" data-diagnostic-tab="drawdown" aria-selected="${state.diagnosticTab === 'drawdown'}" class="${state.diagnosticTab === 'drawdown' ? 'active' : ''}">回撤压力</button>
            <button type="button" role="tab" data-diagnostic-tab="contribution" aria-selected="${state.diagnosticTab === 'contribution'}" class="${state.diagnosticTab === 'contribution' ? 'active' : ''}">收益贡献</button>
          </div></div>
        </div>
        <div class="pf-diagnostic-body" data-pf-diagnostic-body></div>
      </section>

      <section class="panel section-gap">
        <div class="panel-head"><div class="panel-title">成分表现 <span class="sub">目标权重 · 平均权重 · 全区间风险</span></div><div class="panel-actions"><span class="field-hint">${summary.turnover_count ?? 0} 次再平衡 · 年换手 ${metricsAnnualTurnover(summary)}</span></div></div>
        <div class="table-wrap">
          <table class="data-table pf-holdings-table">
            <thead><tr><th>标的</th><th>目标权重</th><th>平均权重</th><th>年化收益</th><th>收益贡献</th><th>风险占比</th><th>波动率</th><th>Sharpe</th><th>Beta</th><th>最大回撤</th><th>行业</th><th>来源</th></tr></thead>
            <tbody>${holdings.map((item) => `<tr class="clickable" data-pf-stock="${esc(item.symbol)}"><td><div class="sym-cell"><div><div class="sym">${esc(item.symbol)}</div><div class="nm">${esc(item.name || '')}</div></div></div></td><td class="num-cell">${fmtNum(item.weight, 1)}%</td><td class="num-cell">${fmtNum(item.average_weight, 1)}%</td><td class="num-cell ${tone(item.annual_return)}">${fmtPct(item.annual_return)}</td><td class="num-cell ${tone(item.return_contribution)}">${fmtPp(item.return_contribution)}</td><td class="num-cell">${fmtPct(item.risk_contribution, 1, false)}</td><td class="num-cell">${fmtPct(item.volatility, 2, false)}</td><td class="num-cell">${fmtNum(item.sharpe, 2)}</td><td class="num-cell">${fmtNum(item.beta, 2)}</td><td class="num-cell">${fmtPct(item.max_drawdown)}</td><td>${esc(item.sector || '—')}</td><td><span class="pf-source">${esc(item.source || '—')}${item.price_basis === 'raw' ? ' · 原始价' : ''}</span></td></tr>`).join('')}</tbody>
          </table>
        </div>
      </section>
      <p class="pf-result-note">历史模拟不代表未来。不同来源与复权口径可能影响结果；未计交易成本、滑点和税费。</p>`;
    setAsOf(payload);
    if (perf.dates?.length) {
      charts.performanceChart($('[data-pf-perf]', results), {
        dates: perf.dates,
        series: { portfolio: perf.portfolio || [], benchmark: perf.benchmark || [] },
        labels: { portfolio: '组合', benchmark: payload.benchmark || '基准' },
      });
    }
    if (dd.dates?.length) {
      charts.drawdownChart($('[data-pf-dd]', results), {
        dates: dd.dates,
        series: { portfolio: dd.portfolio || [], benchmark: dd.benchmark || [] },
        labels: { portfolio: '组合', benchmark: payload.benchmark || '基准' },
      });
    }
    if (annual.length) charts.annualReturnsChart($('[data-pf-annual]', results), annual);
    drawAllocation(payload);
    paintDiagnostic();
  }

  function metricsAnnualTurnover(summary) {
    const value = summary.annual_turnover_est;
    return value === null || value === undefined ? '—' : `${fmtNum(value, 0)}%`;
  }

  async function runBacktest({ focusResults = false } = {}) {
    const holdings = normalizedHoldings(state.holdings).map((item) => ({ symbol: item.symbol, weight: item.weight }));
    if (!holdings.length) {
      ui.toast('请先添加至少一只股票', 'warn');
      return;
    }
    const token = ++state.token;
    state.controller?.abort();
    state.controller = new AbortController();
    state.dirty = false;
    setBusy(true);
    charts.disposeAll();
    state.payload = null;
    results.innerHTML = `<section class="panel">${ui.loadingInline('正在拉取行情并回测，首次可能需要十几秒…')}</section>`;
    try {
      const payload = await api.post('/api/portfolio/backtest', {
        holdings,
        range: state.range,
        rebalance: state.rebalance,
        benchmark: state.benchmark,
      }, { signal: state.controller.signal, timeout: 180000 });
      if (token !== state.token || !isActive() || state.disposed) return;
      if (payload.empty) {
        results.innerHTML = `<section class="panel">${ui.emptyState('无法完成回测', payload.error || payload.message || '共同历史不足。')}</section>`;
        setAsOf(null);
        return;
      }
      renderResults(payload);
      if (focusResults) {
        requestAnimationFrame(() => {
          const top = results.getBoundingClientRect().top + window.scrollY - 22;
          window.scrollTo({ top: Math.max(0, top), behavior: 'smooth' });
        });
      }
    } catch (error) {
      if (error?.name === 'AbortError' || state.disposed || token !== state.token) return;
      setAsOf(null);
      results.innerHTML = `<section class="panel">${ui.errorPanel(error.message || '组合回测失败')}</section>`;
      ui.bindRetry(results, runBacktest);
    } finally {
      if (isActive() && token === state.token) setBusy(false);
    }
  }

  $('[data-pf-add-form]', root).addEventListener('submit', (event) => {
    event.preventDefault();
    if (state.busy) return;
    addSymbol($('[data-pf-symbol-input]', root).value);
  });
  $('[data-pf-equal]', root).addEventListener('click', equalize);
  $('[data-pf-save]', root).addEventListener('click', saveCurrent);
  $('[data-pf-run]', root).addEventListener('click', () => runBacktest({ focusResults: true }));
  $('[data-pf-sample]', root).addEventListener('click', loadSample);
  $('[data-pf-new]', root).addEventListener('click', () => {
    if (state.holdings.length && !window.confirm('新建会清空当前编辑中的组合草稿，确定继续吗？')) return;
    state.id = '';
    state.name = '';
    state.holdings = [];
    state.payload = null;
    charts.disposeAll();
    results.innerHTML = emptyResults();
    persist();
    repaintBuilder();
    setAsOf(null);
  });

  nameInput.addEventListener('input', () => {
    state.name = nameInput.value;
    schedulePersist();
  });

  $$('[data-pf-benchmark] button', root).forEach((button) => button.addEventListener('click', () => {
    if (state.busy || state.benchmark === button.dataset.value) return;
    state.benchmark = button.dataset.value;
    paintConfig();
    schedulePersist();
    markDirty();
  }));
  $$('[data-pf-range] button', root).forEach((button) => button.addEventListener('click', () => {
    if (state.busy || state.range === button.dataset.value) return;
    state.range = button.dataset.value;
    paintConfig();
    schedulePersist();
    markDirty();
  }));
  $$('[data-pf-rebalance] button', root).forEach((button) => button.addEventListener('click', () => {
    if (state.busy || state.rebalance === button.dataset.value) return;
    state.rebalance = button.dataset.value;
    paintConfig();
    schedulePersist();
    markDirty();
  }));

  holdingList.addEventListener('input', (event) => {
    const input = event.target.closest('[data-pf-weight]');
    if (!input) return;
    const holding = state.holdings[Number(input.dataset.pfWeight)];
    if (!holding) return;
    holding.weight = Number(input.value) || 0;
    updateWeightPreview();
    schedulePersist();
    markDirty();
  });

  holdingList.addEventListener('click', (event) => {
    const remove = event.target.closest('[data-pf-remove]');
    if (!remove || state.busy) return;
    state.holdings.splice(Number(remove.dataset.pfRemove), 1);
    renderHoldings();
    schedulePersist();
    if (!state.holdings.length) {
      state.payload = null;
      state.dirty = false;
      charts.disposeAll();
      results.innerHTML = emptyResults();
      setAsOf(null);
      paintRunButton();
    } else {
      markDirty();
    }
  });

  savedList.addEventListener('click', (event) => {
    const remove = event.target.closest('[data-pf-delete]');
    if (remove) {
      const profile = state.saved.find((item) => item.id === remove.dataset.pfDelete);
      if (!profile || !window.confirm(`删除组合「${profile.name}」？此操作只影响本机保存的权重方案。`)) return;
      store.deletePortfolio(profile.id);
      if (state.id === profile.id) state.id = '';
      renderSaved();
      return;
    }
    const load = event.target.closest('[data-pf-load]');
    if (load && !state.busy) loadSaved(load.dataset.pfLoad);
  });

  results.addEventListener('click', (event) => {
    if (event.target.closest('[data-pf-sample-inline]')) {
      loadSample();
      return;
    }
    if (event.target.closest('[data-pf-rerun]')) {
      runBacktest({ focusResults: true });
      return;
    }
    const diagnosticTab = event.target.closest('[data-pf-diagnostic-tabs] [data-diagnostic-tab]');
    if (diagnosticTab && state.payload) {
      const next = diagnosticTab.dataset.diagnosticTab;
      if (next !== state.diagnosticTab) {
        state.diagnosticTab = next;
        paintDiagnostic();
      }
      return;
    }
    const rollingMode = event.target.closest('[data-pf-rolling-mode] [data-rolling-mode]');
    if (rollingMode && state.payload) {
      const next = rollingMode.dataset.rollingMode;
      if (next === state.rollingMode) return;
      state.rollingMode = next;
      $$('[data-pf-rolling-mode] button', results).forEach((button) => {
        button.classList.toggle('active', button.dataset.rollingMode === next);
      });
      drawRollingChart(state.payload);
      return;
    }
    const alloc = event.target.closest('[data-pf-alloc-mode] [data-alloc]');
    if (alloc && state.payload) {
      if (state.allocMode === alloc.dataset.alloc) return;
      state.allocMode = alloc.dataset.alloc;
      drawAllocation(state.payload);
      return;
    }
    if (event.target.closest('button, a, input, select')) return;
    const row = event.target.closest('[data-pf-stock]');
    if (row) navigate(`#/stock/${encodeURIComponent(row.dataset.pfStock)}`);
  });

  const onAbort = () => state.controller?.abort();
  signal.addEventListener('abort', onAbort, { once: true });
  repaintBuilder();
  if (state.holdings.length) runBacktest();

  return () => {
    state.disposed = true;
    state.token += 1;
    state.controller?.abort();
    clearTimeout(persistTimer);
    signal.removeEventListener('abort', onAbort);
  };
}
