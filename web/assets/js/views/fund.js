import { api } from '../api.js';
import { store } from '../store.js';
import * as ui from '../ui.js';
import * as charts from '../charts.js';
import { $, $$, esc, fmtCompact, fmtInt, fmtMoney, fmtNum, fmtPct, fmtPrice, isNum, tone } from '../utils.js';
import { viewHead } from './common.js';

export const meta = {
  title: '基金档案',
  eyebrow: 'FUND DOSSIER',
};

const QUICK_FUNDS = ['VTSAX', 'VGTSX', 'FCNTX', 'SWPPX', 'VOO', 'QQQ', 'SPY', 'BND'];
const RANGES = [
  { key: '1Y', bars: 252 },
  { key: '3Y', bars: 756 },
  { key: '5Y', bars: 1260 },
  { key: 'MAX', bars: 0 },
];
const PERF_ROWS = [
  ['1m', '近1月'],
  ['3m', '近3月'],
  ['6m', '近6月'],
  ['ytd', '今年以来'],
  ['1y', '近1年'],
  ['3y', '近3年'],
  ['5y', '近5年'],
];
const RISK_ROWS = [
  ['annual_return', '年化收益', (value) => fmtPct(value)],
  ['volatility', '年化波动', (value) => fmtPct(value, 2, false)],
  ['sharpe', '夏普比率', (value) => fmtNum(value)],
  ['sortino', '索提诺比率', (value) => fmtNum(value)],
  ['max_drawdown', '最大回撤', (value) => fmtPct(value)],
  ['var_95', 'VaR 95%', (value) => fmtPct(value, 2, false)],
  ['cvar_95', 'CVaR 95%', (value) => fmtPct(value, 2, false)],
  ['beta', 'Beta（对 SPY）', (value) => fmtNum(value)],
  ['correlation', '与 SPY 相关性', (value) => fmtNum(value)],
  ['up_capture', '上涨捕获率', (value) => (isNum(value) ? `${fmtNum(value, 1)}%` : '—')],
  ['down_capture', '下跌捕获率', (value) => (isNum(value) ? `${fmtNum(value, 1)}%` : '—')],
];
const FEE_ROWS = [
  ['management_fee', '管理费'],
  ['distribution_fee', '12b-1 分销费'],
  ['other_expenses', '其他运营费用'],
  ['total_expenses', '年度运营费用合计'],
];

function panel(title, sub, body, actions = '') {
  return `
    <section class="panel">
      <div class="panel-head">
        <div class="panel-title">${esc(title)}${sub ? `<span class="sub">${esc(sub)}</span>` : ''}</div>
        ${actions ? `<div class="panel-actions">${actions}</div>` : ''}
      </div>
      ${body}
    </section>`;
}

function displayFundName(value, fallback) {
  const name = String(value || '').trim().replace(/\s+/g, ' ');
  if (!name) return fallback;
  if (!/[a-z]/.test(name)) {
    return name
      .toLowerCase()
      .replace(/(^|[^a-z])([a-z])/g, (_, prefix, letter) => `${prefix}${letter.toUpperCase()}`)
      .replace(/\bEtf\b/g, 'ETF')
      .replace(/\bUsa\b/g, 'USA')
      .replace(/\bUs\b/g, 'US');
  }
  return name;
}

function compactUsd(value) {
  return isNum(value) ? `${fmtCompact(value).replace(/\s+/g, '')}美元` : '—';
}

function quarterDate(value) {
  const text = String(value || '');
  const match = text.match(/^(March|June|September|December)\s+\d{1,2},\s+(\d{4})$/);
  const quarters = { March: 1, June: 2, September: 3, December: 4 };
  return match ? `Q${quarters[match[1]]} ${match[2]}` : text || '—';
}

function mixChart(id, items) {
  const rows = (items || []).filter((item) => isNum(item.weight));
  if (!rows.length) return ui.emptyState('暂无分类数据', '该申报未披露此项分布。');
  return `<div class="chart" data-mix="${esc(id)}" style="height:${Math.max(120, rows.length * 30 + 24)}px"></div>`;
}

function landing() {
  return `
    <section class="view fund-view">
      ${viewHead({
        eyebrow: meta.eyebrow,
        title: '基金 / ETF 档案',
        sub: 'SEC N-PORT 持仓、497K 招募说明书费率与业绩，叠加净值风险指标，一站式看懂一只基金。',
      })}
      <section class="panel">
        <div class="panel-head"><div class="panel-title">输入份额代码 <span class="sub">零售份额通常为 5 位、以 X/K 结尾</span></div></div>
        <div class="panel-body">
          <div class="symbol-input">
            <input class="input" data-ticker-input placeholder="例如 VTSAX / FCNTX / VOO" maxlength="10" autocomplete="off" spellcheck="false" aria-label="基金代码">
            <button class="btn small" type="button" data-open>${ui.icon('search', 13)}查看档案</button>
          </div>
          <div class="quick-symbols">
            <span class="qlabel">常用基金</span>
            ${QUICK_FUNDS.map((item) => `<button type="button" data-quick="${item}">${item}</button>`).join('')}
          </div>
          <p class="panel-note" style="margin-top:14px">持仓来自 SEC N-PORT 季度申报，费率与目标来自 497K 摘要说明书，净值序列来自 Nasdaq。</p>
        </div>
      </section>
    </section>`;
}

export async function mount(root, params, ctx) {
  const { signal, isActive } = ctx;
  let ticker = String(params.ticker || '').trim().toUpperCase();

  function go(next) {
    window.location.hash = next ? `#/fund/${encodeURIComponent(next)}` : '#/fund';
  }

  function bindPicker() {
    const input = $('[data-ticker-input]', root);
    const open = () => {
      const code = String(input?.value || '').trim().toUpperCase().replace(/\s+/g, '');
      if (!/^[A-Z][A-Z0-9.\-]{0,9}$/.test(code)) {
        ui.toast('请输入有效的基金/ETF 代码', 'warn', 2400);
        return;
      }
      go(code);
    };
    $('[data-open]', root)?.addEventListener('click', open);
    input?.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        open();
      }
    });
    root.addEventListener('click', (event) => {
      const quick = event.target.closest('[data-quick]');
      if (quick) go(quick.dataset.quick);
    });
  }

  if (!ticker) {
    root.innerHTML = landing();
    bindPicker();
    return undefined;
  }

  root.innerHTML = `
    <section class="view fund-view">
      ${viewHead({ eyebrow: meta.eyebrow, title: ticker, sub: '正在拉取 SEC 申报与净值序列，首次查询需要读取多份公开文件…' })}
      <div class="panel">${ui.loadingInline('正在解析 N-PORT 持仓与 497K 招募说明书…')}</div>
    </section>`;

  const watch = store.watchlist();
  let data;
  try {
    data = await api.get(`/api/funds/${encodeURIComponent(ticker)}?watch=${encodeURIComponent(watch.join(','))}`, {
      signal,
      timeout: 150000,
    });
  } catch (error) {
    if (error?.name === 'AbortError') return undefined;
    root.innerHTML = `
      <section class="view fund-view">
        ${viewHead({ eyebrow: meta.eyebrow, title: ticker, sub: '基金档案未能生成。', actions: '<a class="btn small" href="#/fund">切换基金</a>' })}
        <div class="panel">${ui.errorPanel(error.message || '基金数据加载失败')}</div>
      </section>`;
    ui.bindRetry(root, () => ctx.reload());
    return undefined;
  }
  if (!isActive()) return undefined;

  const profile = data.profile || {};
  const expense = data.expense || {};
  const analytics = data.analytics || {};
  const perf = data.performance || {};
  const risk = data.risk || {};
  const horizons = risk.horizons || {};
  const horizonKeys = Object.keys(horizons);
  const expenseRatio = isNum(expense.total_expenses) ? expense.total_expenses : profile.expense_ratio;
  const fundName = displayFundName(data.fund_name || profile.name, ticker);
  const navSeries = data.return_series || [];
  const benchSeries = data.benchmark?.series || [];
  const quote = data.quote || {};
  const priceLabel = quote.kind === 'market_price' ? '收盘市价' : quote.kind === 'nav' ? '单位净值' : '最新价格';
  const basisLabel = data.return_basis === 'adjusted' ? 'Nasdaq 复权收益' : '价格收益（未含分红）';
  const benchmarkLabel = `${data.benchmark?.symbol || 'SPY'}${data.benchmark?.basis === 'adjusted' ? ' 复权' : ' 价格'}`;
  const basisWarning = navSeries.length && benchSeries.length && !data.benchmark?.comparable
    ? '基金与 SPY 的复权口径不同：SPY 价格曲线未含分红，不用于判断超额收益；相对风险指标暂不计算。'
    : null;
  const riskRows = RISK_ROWS.filter(([key]) => data.benchmark?.comparable || !['beta', 'correlation', 'up_capture', 'down_capture'].includes(key));
  const watched = watch.includes(ticker);
  const flows = (data.flows || []).filter((item) => isNum(item.sales) || isNum(item.redemption) || isNum(item.reinvestment));

  root.innerHTML = `
    <section class="view fund-view">
      ${viewHead({
        eyebrow: meta.eyebrow,
        title: fundName,
        sub: [ticker, data.registrant, expense.adviser]
          .filter(Boolean)
          .join(' · '),
        actions: `
          <button class="btn small ${watched ? 'ghost' : ''}" type="button" data-watch>${ui.starIcon(watched, 13)}${watched ? '已加自选' : '加入自选'}</button>
          <button class="btn small" type="button" data-switch>切换基金</button>`,
      })}
      ${ui.warnBanner([data.identity_warning, basisWarning])}

      <div class="stat-strip">
        ${[
          [priceLabel, fmtPrice(quote.value), `${quote.source === 'daily_history' ? '日线' : '档案快照'} · ${quote.as_of || '—'}`],
          ['年度运营费用', isNum(expenseRatio) ? `${fmtNum(expenseRatio)}%` : '—', expense.filed ? `${expense.form} · ${expense.filed}` : 'Nasdaq 档案'],
          ['基金净资产', compactUsd(data.net_assets), data.period_end ? `报告期 ${data.period_end}` : '未披露'],
          ['持仓数量', fmtInt(analytics.positions), analytics.basis === 'nport_full' ? 'N-PORT 全量持仓' : '仅披露前十大'],
          ['前十大权重', isNum(analytics.top10) ? `${fmtNum(analytics.top10, 1)}%` : '—', analytics.basis === 'nport_full' ? `前二十 ${isNum(analytics.top20) ? fmtNum(analytics.top20, 1) : '—'}%` : '仅公开前十大，不代表全持仓'],
          ['有效持仓数', fmtNum(analytics.effective_positions, 1), isNum(analytics.hhi) ? `HHI ${fmtInt(analytics.hhi)}` : '集中度赫芬达尔指数'],
        ]
          .map(
            ([label, value, sub]) => `
              <div class="stat-card">
                <div class="stat-label"><span>${esc(label)}</span></div>
                <div class="stat-value">${esc(value)}</div>
                <div class="stat-sub">${esc(sub || '')}</div>
              </div>`,
          )
          .join('')}
      </div>

      <div class="chip-row">
        <span class="field-hint">${esc(basisLabel)}</span>
        ${PERF_ROWS.filter(([key]) => isNum(perf[key]))
          .map(([key, label]) => `<span class="chip" style="cursor:default">${label}<span class="chip-sub ${tone(perf[key])}" style="margin-left:6px">${fmtPct(perf[key])}</span></span>`)
          .join('') || '<span class="field-hint">暂无可用区间收益</span>'}
      </div>

      ${panel(
        '区间表现与市场参考',
        `${basisLabel} · 共同交易日归一为 100 · ${benchmarkLabel}`,
        `<div class="chart-toolbar"><div class="seg" data-range-seg>${RANGES.map(
          (item) => `<button type="button" data-range="${item.key}" class="${item.key === '1Y' ? 'active' : ''}">${item.key}</button>`,
        ).join('')}</div></div><div class="chart-body">${
          navSeries.length > 40 ? '<div class="chart" data-nav style="height:330px"></div>' : ui.emptyState('暂无净值序列', '该基金的净值历史不足。')
        }</div>`,
      )}

      <div class="grid-2">
        ${panel(
          '费率拆解',
          expense.form ? `来源 ${expense.form} 摘要说明书` : '招募说明书缺失',
          `<div class="panel-body">
            ${FEE_ROWS.filter(([key]) => isNum(expense[key])).length
              ? `<table class="data-table"><tbody>${FEE_ROWS.filter(([key]) => isNum(expense[key]))
                  .map(([key, label]) => `<tr><td>${label}</td><td class="num" style="text-align:right">${fmtNum(expense[key])}%</td></tr>`)
                  .join('')}</tbody></table>`
              : '<p class="field-hint">未能解析费率表。</p>'}
            <div class="kv-line"><span>组合换手率</span><b>${isNum(expense.portfolio_turnover) ? `${fmtNum(expense.portfolio_turnover, 0)}%` : '—'}</b></div>
            <div class="kv-line"><span>业绩基准</span><b>${esc(expense.benchmark || '—')}</b></div>
            <div class="kv-line"><span>投资顾问</span><b>${esc(expense.adviser || '—')}</b></div>
            ${(expense.managers || []).map((item) => `<div class="kv-line"><span>${esc(item.name)}</span><b>${esc(item.role || '基金经理')} · 自 ${esc(item.since || '—')}</b></div>`).join('')}
          </div>`,
        )}
        ${panel(
          '1 万美元成本示例',
          '按 5% 年化假设、费用不变的官方口径',
          `<div class="panel-body">
            ${Object.keys(expense.cost_example || {}).length
              ? `<table class="data-table"><tbody>${Object.entries(expense.cost_example)
                  .map(([key, value]) => `<tr><td>${esc(key.replace('y', ' 年'))}</td><td class="num" style="text-align:right">${fmtMoney(value, 0)}</td></tr>`)
                  .join('')}</tbody></table>`
              : '<p class="field-hint">该招募说明书未提供成本示例。</p>'}
            <p class="panel-note">持有期越长，费用对复利的侵蚀越大；把它和「年度运营费用」一起看，比只看单年费率更接近真实成本。</p>
          </div>`,
        )}
      </div>

      <div class="grid-2">
        ${panel(
          '说明书披露的年化回报',
          '基金 vs 业绩基准（税前）',
          `<div class="panel-body">${
            (expense.average_returns?.periods || []).length
              ? `<table class="data-table"><thead><tr><th>区间</th><th>基金</th><th>基准</th><th>超额</th></tr></thead><tbody>
                  ${expense.average_returns.periods
                    .map((period, index) => {
                      const fund = expense.average_returns.fund?.[index];
                      const bench = expense.average_returns.benchmark?.[index];
                      return `<tr><td>${period} 年</td><td class="num">${fmtPct(fund)}</td><td class="num">${fmtPct(bench)}</td><td class="num ${tone(isNum(fund) && isNum(bench) ? fund - bench : null)}">${isNum(fund) && isNum(bench) ? fmtPct(fund - bench) : '—'}</td></tr>`;
                    })
                    .join('')}</tbody></table>`
              : '<p class="field-hint">未解析到平均年化回报表。</p>'
          }
          ${expense.quarter_extremes?.best || expense.quarter_extremes?.worst ? `<p class="panel-note">最佳季度 ${fmtPct(expense.quarter_extremes?.best?.return)}（${esc(quarterDate(expense.quarter_extremes?.best?.date))}） · 最差季度 ${fmtPct(expense.quarter_extremes?.worst?.return)}（${esc(quarterDate(expense.quarter_extremes?.worst?.date))}）</p>` : ''}
          </div>`,
        )}
        ${panel(
          '历年回报',
          '497K 披露的日历年收益',
          `<div class="panel-body">${
            (expense.annual_returns || []).length
              ? '<div class="chart" data-annual style="height:300px"></div>'
              : ui.emptyState('该说明书未提供年度柱图', '部分基金公司只在年报中披露逐年收益。')
          }</div>`,
        )}
      </div>

      ${panel(
        '风险画像',
        risk.as_of ? `${basisLabel} · 截至 ${risk.as_of}` : '历史行情不足',
        horizonKeys.length
          ? `<div class="table-wrap"><table class="data-table metrics-table"><thead><tr><th>指标</th>${horizonKeys.map((key) => `<th>${key}</th>`).join('')}</tr></thead><tbody>${riskRows.map(([key, label, format]) => `<tr><td>${label}</td>${horizonKeys.map((period) => `<td class="num">${format(horizons[period]?.[key])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`
          : '<div class="panel-body"><p class="field-hint">历史序列不足以计算风险指标。</p></div>',
      )}

      <div class="grid-2">
        ${panel(
          '回撤轨迹',
          risk.drawdown?.trough_date ? `最深 ${fmtPct(risk.drawdown.max)} · 谷底 ${risk.drawdown.trough_date}` : '距历史峰值回落',
          `<div class="chart-body">${
            (risk.drawdown?.series || []).length
              ? '<div class="chart" data-drawdown style="height:270px"></div>'
              : ui.emptyState('暂无回撤数据', '需要更长的净值历史。')
          }</div>`,
        )}
        ${panel(
          '资产与地域分布',
          analytics.basis === 'nport_full' ? 'N-PORT 全量持仓权重' : '仅前十大持仓',
          `<div class="panel-body">${mixChart('asset', analytics.asset_mix)}${mixChart('country', analytics.country_mix)}</div>`,
        )}
      </div>

      ${panel(
        '持仓明细',
        `展示前 ${Math.min(30, data.holdings?.length || 0)} 项 · 市值单位：美元`,
        (data.holdings || []).length
          ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>持仓</th><th>代码</th><th>权重</th><th>市值</th><th>地区</th></tr></thead><tbody>${data.holdings
              .slice(0, 30)
              .map((item) => `<tr><td>${esc(item.title || item.name || '—')}</td><td>${item.symbol ? `<a class="link" href="#/stock/${encodeURIComponent(item.symbol)}">${esc(item.symbol)}</a>` : '—'}</td><td class="num">${isNum(item.weight) ? `${fmtNum(item.weight)}%` : '—'}</td><td class="num">${isNum(item.value) ? `${fmtCompact(item.value)}` : '—'}</td><td>${esc(item.country || '—')}</td></tr>`)
              .join('')}</tbody></table></div>`
          : '<div class="panel-body"><p class="field-hint">该基金暂无可用的 N-PORT 持仓。</p></div>',
        `<span class="pill info">${data.source === 'sec_edgar_nport' ? 'SEC EDGAR' : 'Nasdaq'}</span>`,
      )}

      <div class="grid-2">
        ${panel(
          '与我的自选重叠',
          watch.length ? `自选 ${watch.length} 只` : '尚未添加自选',
          `<div class="panel-body">${
            (data.overlap || []).length
              ? data.overlap
                  .map((item) => `<div class="kv-line"><a class="link" href="#/stock/${encodeURIComponent(item.symbol)}">${esc(item.symbol)}</a><b>${fmtNum(item.weight)}%</b></div>`)
                  .join('')
              : '<p class="field-hint">未发现已识别持仓与你的自选重叠。</p>'
          }<p class="panel-note">仅统计可识别代码；同名多份额或无法唯一匹配的证券不计入，结果可能低估重叠。</p></div>`,
        )}
        ${panel(
          '近三月申赎',
          data.period_end ? `报告期 ${data.period_end}` : 'N-PORT 月度资金流',
          `<div class="panel-body">${
            flows.length
              ? `<table class="data-table"><thead><tr><th>月序</th><th>申购</th><th>赎回</th><th>再投资</th><th>净申赎</th></tr></thead><tbody>${flows
                  .map((item) => `<tr><td>第 ${item.month} 月</td><td class="num">${fmtCompact(item.sales)}</td><td class="num">${fmtCompact(item.redemption)}</td><td class="num">${fmtCompact(item.reinvestment)}</td><td class="num ${tone(item.net_flow)}">${fmtCompact(item.net_flow)}</td></tr>`)
                  .join('')}</tbody></table><p class="panel-note">单位：美元。按报告期内月份先后排列；净申赎 = 申购 − 赎回，分红再投资单列、不计入现金净流量。</p>`
              : '<p class="field-hint">本次申报未披露申赎数据。</p>'
          }</div>`,
        )}
      </div>

      ${panel(
        '投资目标与策略',
        expense.filed ? `${expense.form} · ${expense.filed}` : '招募说明书',
        `<div class="panel-body">
          ${expense.objective ? `<p class="prose"><b>目标：</b>${esc(expense.objective)}</p>` : ''}
          ${expense.strategies ? `<p class="prose">${esc(expense.strategies)}</p>` : ''}
          ${!expense.objective && !expense.strategies ? '<p class="field-hint">未解析到目标与策略段落。</p>' : ''}
          <p class="panel-note">持仓来自 SEC 季度申报，存在披露滞后；共同基金展示单位净值，ETF 展示市价。收益与风险采用标注口径，未提供复权数据时不计分红。区间收益为累计值，月/年区间按 21/252 个交易日近似；今年以来从上一年末计算，仅供研究参考。</p>
        </div>`,
      )}
    </section>`;

  function renderNav(rangeKey) {
    const limit = RANGES.find((item) => item.key === rangeKey)?.bars || 0;
    const nav = (limit ? navSeries.slice(-limit) : navSeries).filter((bar) => isNum(bar.c) && bar.c > 0);
    if (!nav.length) return;
    const benchMap = new Map(benchSeries.filter((bar) => isNum(bar.c) && bar.c > 0).map((bar) => [bar.t, bar.c]));
    const common = nav.filter((bar) => benchMap.has(bar.t));
    const aligned = common.length > 1 ? common : nav;
    const firstNav = aligned[0].c;
    const series = { [ticker]: aligned.map((bar) => Number(((bar.c / firstNav) * 100).toFixed(3))) };
    if (common.length > 1) {
      const firstBench = benchMap.get(aligned[0].t);
      series.benchmark = aligned.map((bar) => Number(((benchMap.get(bar.t) / firstBench) * 100).toFixed(3)));
    }
    charts.performanceChart($('[data-nav]', root), {
      dates: aligned.map((bar) => bar.t),
      series,
      labels: { [ticker]: ticker, benchmark: benchmarkLabel },
      benchmarkName: benchmarkLabel,
    });
  }

  renderNav('1Y');
  if ((expense.annual_returns || []).length) {
    charts.barListChart(
      $('[data-annual]', root),
      [...expense.annual_returns].reverse().map((item) => ({ name: String(item.year), value: item.return })),
    );
  }
  if ((risk.drawdown?.series || []).length) {
    charts.drawdownChart($('[data-drawdown]', root), {
      dates: risk.drawdown.series.map((item) => item.date),
      series: { [ticker]: risk.drawdown.series.map((item) => item.value) },
      labels: { [ticker]: ticker },
    });
  }
  $$('[data-mix]', root).forEach((el) => {
    const source = el.dataset.mix === 'asset' ? analytics.asset_mix : analytics.country_mix;
    charts.barListChart(el, (source || []).map((item) => ({ name: item.label, value: item.weight })), { tone: 'allocation' });
  });

  $('[data-watch]', root)?.addEventListener('click', () => {
    store.rememberFund(ticker);
    const added = store.toggleWatch(ticker);
    ui.toast(added ? `已把 ${ticker} 加入自选` : `已从自选移除 ${ticker}`, 'success', 2200);
  });
  $('[data-switch]', root)?.addEventListener('click', () => go(''));
  $('[data-range-seg]', root)?.addEventListener('click', (event) => {
    const button = event.target.closest('[data-range]');
    if (!button) return;
    $$('[data-range-seg] [data-range]', root).forEach((item) => item.classList.toggle('active', item === button));
    renderNav(button.dataset.range);
  });

  const onWatchStore = (event) => {
    if (event.detail?.type === 'watchlist') ctx.reload();
  };
  window.addEventListener('starmap:store', onWatchStore);
  return () => window.removeEventListener('starmap:store', onWatchStore);
}
