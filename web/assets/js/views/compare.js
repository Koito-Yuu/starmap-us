import { api } from '../api.js';
import * as ui from '../ui.js';
import * as charts from '../charts.js';
import { $, $$, esc, fmtPct, fmtPrice, fmtNum, isNum, tone } from '../utils.js';
import { asOfBadge, viewHead } from './common.js';

export const meta = {
  title: '多股对比',
  eyebrow: 'RELATIVE PERFORMANCE',
};

const RANGES = ['1M', '3M', '6M', 'YTD', '1Y', '3Y', '5Y', 'MAX'];
const MAX_SYMBOLS = 6;
const QUICK_SYMBOLS = ['AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'TSLA', 'AVGO', 'AMD', 'JPM'];

const METRIC_ROWS = [
  { key: 'price', label: '最新价', format: (value) => fmtPrice(value), best: null },
  { key: 'change_pct', label: '当日涨跌', format: (value) => fmtPct(value), best: 'max', tone: true },
  { key: 'total_return', label: '区间收益', hint: '区间累计涨跌幅', format: (value) => fmtPct(value), best: 'max', tone: true },
  { key: 'annual_return', label: '年化收益', hint: '按 252 个交易日折算', format: (value) => fmtPct(value), best: 'max', tone: true },
  { key: 'volatility', label: '年化波动率', hint: '日收益标准差年化', format: (value) => fmtPct(value, 2, false), best: 'min' },
  { key: 'sharpe', label: '夏普比率', hint: '(年化收益 - 无风险利率) / 波动率', format: (value) => fmtNum(value, 2), best: 'max' },
  { key: 'sortino', label: '索提诺比率', hint: '仅惩罚下行波动的风险调整收益', format: (value) => fmtNum(value, 2), best: 'max' },
  { key: 'max_drawdown', label: '最大回撤', hint: '区间内从峰值到谷值的最大跌幅', format: (value) => fmtPct(value), best: 'max' },
  { key: 'var_95', label: 'VaR 95%', hint: '95% 置信度下的单日最大预期亏损', format: (value) => fmtPct(value, 2, false), best: 'min' },
  { key: 'cvar_95', label: 'CVaR 95%', hint: '尾部 5% 极端亏损的平均值', format: (value) => fmtPct(value, 2, false), best: 'min' },
  { key: 'beta', label: 'Beta', hint: '相对 SPY 的系统性风险暴露', format: (value) => fmtNum(value, 2), best: null },
  { key: 'correlation', label: '与 SPY 相关性', hint: '日收益相关系数', format: (value) => fmtNum(value, 2), best: null },
];

function buildHash(symbols, range) {
  return `#/compare?symbols=${encodeURIComponent(symbols.join(','))}&range=${encodeURIComponent(range)}`;
}

function sanitizeSymbols(raw) {
  const list = String(raw || '')
    .split(',')
    .map((item) => item.trim().toUpperCase())
    .filter(Boolean);
  return Array.from(new Set(list)).slice(0, MAX_SYMBOLS);
}

function sourceName(name) {
  return name && name !== '—' ? name : '';
}

function bestValues(metrics, key, direction) {
  const values = metrics.map((item) => item[key]).filter(isNum).map(Number);
  if (!values.length) return new Set();
  const target = direction === 'max' ? Math.max(...values) : Math.min(...values);
  return new Set(metrics.filter((item) => isNum(item[key]) && Number(item[key]) === target).map((item) => item.symbol));
}

export async function mount(root, params, ctx) {
  const { signal, isActive } = ctx;
  let symbols = sanitizeSymbols(params.symbols || 'AAPL,MSFT,NVDA');
  if (!symbols.length) symbols = ['AAPL', 'MSFT', 'NVDA'];
  let range = String(params.range || '1Y').toUpperCase();
  if (!RANGES.includes(range)) range = '1Y';

  root.innerHTML = `
    <section class="view">
      ${viewHead({
        eyebrow: meta.eyebrow,
        title: '多股对比',
        sub: '归一化走势、风险收益指标与相关性矩阵，横向评估相对强弱。',
        actions: '<span class="as-of"><span class="dot"></span>正在计算对比指标…</span>',
      })}
      <div class="panel">${ui.loadingInline('正在拉取历史行情并计算风险指标…')}</div>
    </section>`;

  let data;
  try {
    data = await api.get(`/api/compare?symbols=${encodeURIComponent(symbols.join(','))}&range=${encodeURIComponent(range)}`, {
      signal,
      timeout: 120000,
    });
  } catch (error) {
    if (error?.name === 'AbortError') return undefined;
    root.innerHTML = `
      <section class="view">
        ${viewHead({ eyebrow: meta.eyebrow, title: '多股对比', sub: '对比计算未能完成。' })}
        <div class="panel">${ui.errorPanel(error.message || '对比数据加载失败')}</div>
      </section>`;
    ui.bindRetry(root, () => ctx.reload());
    return undefined;
  }
  if (!isActive()) return undefined;

  const metrics = data.metrics || [];
  const quotes = data.quotes || {};
  const names = Object.fromEntries((data.symbols || []).map((item) => [item.symbol, item.name]));
  const labels = Object.fromEntries(symbols.map((symbol) => [symbol, names[symbol] || symbol]));
  if (data.benchmark) labels.benchmark = data.benchmark;
  const hasChart = (data.performance?.dates || []).length && Object.keys(data.performance?.series || {}).length;
  const hasDrawdown = (data.drawdown?.dates || []).length && Object.keys(data.drawdown?.series || {}).length;
  const fallbackSymbols = Object.entries(data.sources || {})
    .filter(([, source]) => source === 'nasdaq')
    .map(([symbol]) => symbol);
  const sourceWarnings = fallbackSymbols.length
    ? [`${fallbackSymbols.join('、')} 使用 Nasdaq 日线备用行情；指标按共同交易日计算。`]
    : [];

  root.innerHTML = `
    <section class="view">
      ${viewHead({
        eyebrow: meta.eyebrow,
        title: '多股对比',
        sub: `${symbols.length} 只标的 · ${range} 区间 · 归一化基准 100`,
        actions: `${asOfBadge(data.as_of)}<span class="pill info">SPY 基准</span>`,
      })}
      ${ui.warnBanner([...(data.errors || []), ...sourceWarnings])}

      <div class="panel symbol-editor">
        <div class="symbol-chips" data-chips>
          ${symbols
            .map((symbol) => {
              const quote = quotes[symbol] || {};
              const missing = !metrics.some((item) => item.symbol === symbol);
              return `
                <span class="sym-chip ${missing ? 'is-missing' : ''}">
                  ${esc(symbol)}
                  ${missing ? '<span class="s-price">数据缺失</span>' : `<span class="s-price">${fmtPrice(quote.price)}</span><span class="s-chg ${tone(quote.change_pct)}">${fmtPct(quote.change_pct)}</span>`}
                  <button type="button" data-remove="${esc(symbol)}" aria-label="移除 ${esc(symbol)}">${ui.icon('x', 10)}</button>
                </span>`;
            })
            .join('')}
        </div>
        <div class="symbol-input">
          <input class="input" type="text" data-symbol-input placeholder="输入代码，如 TSLA" maxlength="12" autocomplete="off" spellcheck="false">
          <button type="button" class="btn small" data-add>${ui.icon('plus', 13)}添加</button>
        </div>
      </div>
      <div class="quick-symbols">
        <span class="qlabel">快速添加</span>
        ${QUICK_SYMBOLS.map(
          (symbol) => `<button type="button" data-quick="${symbol}" ${symbols.includes(symbol) ? 'disabled' : ''}>${symbol}</button>`,
        ).join('')}
      </div>

      <div class="compare-main">
        <section class="panel">
          <div class="panel-head">
            <div class="panel-title">归一化走势 <span class="sub">起点 = 100</span></div>
            <div class="panel-actions">
              <div class="seg" data-range-seg>
                ${RANGES.map((item) => `<button type="button" data-range="${item}" class="${item === range ? 'active' : ''}">${item}</button>`).join('')}
              </div>
            </div>
          </div>
          <div class="chart-body">
            ${
              hasChart
                ? '<div class="chart" data-performance style="height:352px"></div>'
                : ui.emptyState('暂无可比行情', '所选标的没有足够重合的历史行情。')
            }
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div class="panel-title">相关性矩阵 <span class="sub">日收益 · Pearson</span></div>
          </div>
          <div class="chart-body">
            ${
              (data.correlation?.symbols || []).length > 1
                ? '<div class="chart" data-correlation style="height:352px"></div>'
                : ui.emptyState('需要至少两只标的', '添加更多标的后可计算收益相关性。')
            }
          </div>
        </section>
      </div>

      <div class="compare-insights">
        <section class="panel">
          <div class="panel-head">
            <div class="panel-title">回撤曲线 <span class="sub">距区间峰值回落</span></div>
            <div class="panel-actions"><span class="field-hint">0% 为新高</span></div>
          </div>
          <div class="chart-body">
            ${
              hasDrawdown
                ? '<div class="chart" data-drawdown style="height:286px"></div>'
                : ui.emptyState('暂无回撤数据', '所选区间的历史行情不足。')
            }
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div class="panel-title">风险收益定位 <span class="sub">年化波动 × 年化收益</span></div>
            <div class="panel-actions"><span class="field-hint">越靠左上越优</span></div>
          </div>
          <div class="chart-body">
            ${
              metrics.length
                ? '<div class="chart" data-risk-return style="height:286px"></div>'
                : ui.emptyState('暂无可绘制的风险指标', '需要至少一只标的拥有足够的历史行情。')
            }
          </div>
        </section>
      </div>

      <section class="panel">
        <div class="panel-head">
          <div class="panel-title">风险收益对比 <span class="sub">区间 ${esc(range)}</span></div>
          <div class="panel-actions"><span class="field-hint">高亮为同组最优</span></div>
        </div>
        ${
          metrics.length
            ? `<div class="table-wrap">
                <table class="data-table metrics-table">
                  <thead>
                    <tr>
                      <th>指标</th>
                      ${metrics.map((item) => `<th>${esc(item.symbol)}${sourceName(item.name) ? `<span class="m-label">${esc(item.name)}</span>` : ''}</th>`).join('')}
                    </tr>
                  </thead>
                  <tbody>
                    ${METRIC_ROWS.map((row) => {
                      const cells = metrics
                        .map((item) => {
                          const value = row.key === 'price' || row.key === 'change_pct' ? quotes[item.symbol]?.[row.key] : item[row.key];
                          const toneClass = row.tone ? tone(value) : '';
                          return `<td class="${toneClass}" data-metric="${row.key}" data-symbol="${esc(item.symbol)}">${row.format(value)}</td>`;
                        })
                        .join('');
                      return `<tr><td>${row.label}${row.hint ? `<span class="m-label">${esc(row.hint)}</span>` : ''}</td>${cells}</tr>`;
                    }).join('')}
                  </tbody>
                </table>
              </div>
              <div class="metric-explainer">
                <p><b>夏普比率</b> 衡量单位总风险获得的超额收益，越高越好。</p>
                <p><b>索提诺比率</b> 只考虑下行波动，更贴近实际亏损风险。</p>
                <p><b>最大回撤</b> 区间内最深的净值回撤，越接近 0 越好。</p>
                <p><b>VaR / CVaR</b> 历史模拟法估计的单日尾部亏损，越低越好。</p>
                <p><b>Beta</b> 相对 SPY 的系统性风险，大于 1 表示波动放大。</p>
                <p><b>相关性</b> 分散化参考，组合内低相关标的越多越好。</p>
              </div>`
            : ui.emptyState('对比结果为空', '所选标的均未能获取足够的历史行情，请更换代码或区间。')
        }
      </section>
    </section>`;

  if (hasChart) {
    charts.performanceChart($('[data-performance]', root), {
      dates: data.performance.dates,
      series: data.performance.series,
      labels,
      benchmarkName: data.benchmark || 'SPY',
    });
  }
  if (hasDrawdown) {
    charts.drawdownChart($('[data-drawdown]', root), {
      dates: data.drawdown.dates,
      series: data.drawdown.series,
      labels,
    });
  }
  if (metrics.length) {
    charts.riskReturnScatter($('[data-risk-return]', root), metrics, { labels });
  }
  if ((data.correlation?.symbols || []).length > 1) {
    charts.correlationHeatmap($('[data-correlation]', root), data.correlation);
  }

  METRIC_ROWS.forEach((row) => {
    if (!row.best) return;
    const best = bestValues(metrics, row.key, row.best);
    $$(`[data-metric="${row.key}"]`, root).forEach((cell) => {
      if (best.has(cell.dataset.symbol)) cell.classList.add('best');
    });
  });

  function go(nextSymbols, nextRange = range) {
    window.location.hash = buildHash(nextSymbols, nextRange);
  }

  const input = $('[data-symbol-input]', root);
  function addSymbol(value) {
    const code = String(value || '').trim().toUpperCase().replace(/\s+/g, '');
    if (!code) return;
    if (!/^[A-Z][A-Z0-9.-]{0,11}$/.test(code)) {
      ui.toast('请输入有效的股票代码', 'warn', 2200);
      return;
    }
    if (symbols.includes(code)) {
      ui.toast(`${code} 已在对比列表中`, 'info', 1800);
      return;
    }
    if (symbols.length >= MAX_SYMBOLS) {
      ui.toast(`最多同时对比 ${MAX_SYMBOLS} 只标的`, 'warn', 2200);
      return;
    }
    go([...symbols, code]);
  }

  $('[data-add]', root).addEventListener('click', () => addSymbol(input.value));
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      addSymbol(input.value);
    }
  });

  root.addEventListener('click', (event) => {
    const remove = event.target.closest('[data-remove]');
    if (remove) {
      if (symbols.length <= 1) {
        ui.toast('至少保留一只标的', 'warn', 1800);
        return;
      }
      go(symbols.filter((symbol) => symbol !== remove.dataset.remove));
      return;
    }
    const quick = event.target.closest('[data-quick]');
    if (quick && !quick.disabled) {
      addSymbol(quick.dataset.quick);
      return;
    }
    const rangeButton = event.target.closest('[data-range-seg] [data-range]');
    if (rangeButton && rangeButton.dataset.range !== range) {
      go(symbols, rangeButton.dataset.range);
    }
  });

  return undefined;
}
