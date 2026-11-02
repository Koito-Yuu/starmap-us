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
  fmtMoney,
  fmtMoneyCompact,
  fmtNum,
  fmtPct,
  fmtPrice,
  isNum,
  safeUrl,
  tone,
} from '../utils.js';
import { statCard, viewHead } from './common.js';
import { renderMdaReport } from './mda-report.js';
import {
  CHANNEL_PARAMS,
  DEFAULT_INDICATOR_PARAMS,
  PARAM_RANGES,
  STUDY_PARAMS,
  TREND_PARAMS,
  channelSummary,
  formatParam,
  sanitizeIndicatorParams,
  studySummary,
  trendSummary,
} from '../technical.js';

export const meta = {
  title: '个股研究',
  eyebrow: 'EQUITY RESEARCH',
};

const RANGES = ['1D', '5D', '1M', '3M', '6M', 'YTD', '1Y', '3Y', '5Y', 'MAX'];

const CHANNELS = {
  none: { name: '不叠加通道', summary: () => '' },
  bb: {
    name: '布林通道',
    summary: (p) => channelSummary('bb', p),
    formula: (p) => `SMA${p.bb_period} ± ${formatParam(p.bb_mult)} × 收盘价总体标准差`,
    text: '观察波动扩张与相对位置。触及上轨不等于卖出，低波动也不决定突破方向。',
  },
  kc: {
    name: '肯特纳通道',
    summary: (p) => channelSummary('kc', p),
    formula: (p) => `EMA${p.kc_period} ± ${formatParam(p.kc_mult)} × Wilder ATR${p.kc_atr_period}`,
    text: '用真实波幅过滤价格噪声，较布林带更平稳；趋势行情可能长期沿上轨或下轨运行。',
  },
  donchian: {
    name: '唐奇安通道',
    summary: (p) => channelSummary('donchian', p),
    formula: (p) => `上轨 = 前${p.donchian_period}根最高价；下轨 = 前${p.donchian_period}根最低价`,
    text: '不含当前K线，可观察收盘是否突破先前区间；跳空和假突破仍需成交量、趋势强度验证。',
  },
  regression: {
    name: '滚动回归通道',
    summary: (p) => channelSummary('regression', p),
    formula: (p) => `过去${p.regression_period}根OLS拟合的当前端点 ± ${formatParam(p.regression_mult)} × 残差均方根`,
    text: '每根独立使用当时可见历史，不用最后一段回归线重画过去。带宽不是价格预测置信区间。',
  },
  vwap: {
    name: '滚动量价通道',
    summary: (p) => channelSummary('vwap', p),
    formula: (p) => `${p.vwap_period}根 HLC3 成交量加权均价 ± ${formatParam(p.vwap_mult)} × 加权标准差`,
    text: '以成交量估算阶段成本分布，不是日内重置VWAP或逐笔成交成本；缺量或总量为零时留空。',
  },
  adaptive: {
    name: '自适应波动通道',
    summary: (p) => channelSummary('adaptive', p),
    formula: (p) => `KAMA(${p.adaptive_period},${p.adaptive_fast},${p.adaptive_slow}) ± ATR${p.adaptive_atr_period} × (${formatParam(p.adaptive_mult)} + ER${p.adaptive_period})`,
    text: '组合实验：KAMA随方向效率调速，ATR与ER共同调节带宽。公式透明，未经过策略收益验证。',
  },
};
const TRENDS = {
  none: { name: '不叠加趋势线', summary: () => '' },
  supertrend: {
    name: 'Supertrend',
    summary: (p) => trendSummary('supertrend', p),
    formula: (p) => `HL2 ± ${formatParam(p.supertrend_mult)} × ATR${p.supertrend_period}，按前收盘与前轨迹递推`,
    text: '初始方向约定为上行，分段显示上行支撑与下行阻力，收盘穿越触发切换；横盘时容易反复翻转。',
  },
  kama: {
    name: 'KAMA 自适应均线',
    summary: (p) => trendSummary('kama', p),
    formula: (p) => `ER = ${p.kama_period}根净变动 / 路径长度；SC = [ER × (2/${p.kama_fast + 1} − 2/${p.kama_slow + 1}) + 2/${p.kama_slow + 1}]²`,
    text: '用方向效率在快慢平滑之间切换。初始种子取效率窗口均价，递推指标会受载入历史长度影响。',
  },
};
const STUDIES = {
  none: { name: '不添加副图', summary: () => '' },
  adx: {
    name: 'ADX / DMI',
    summary: (p) => studySummary('adx', p),
    formula: (p) => `±DI = 100 × 平滑${p.adx_period}根±DM / ATR；ADX = 平滑${p.adx_period}根方向差异DX`,
    text: 'ADX衡量强度而非方向，25仅作观察参考；方向看+DI与−DI，不是买卖评分。',
  },
  stochastic: {
    name: '慢速随机指标',
    summary: (p) => studySummary('stochastic', p),
    formula: (p) => `%K = SMA${p.stoch_k}[100 × (收盘 − LL${p.stoch_period}) / (HH${p.stoch_period} − LL${p.stoch_period})]；%D = SMA${p.stoch_d}(%K)`,
    text: '20/80为相对位置参考。强趋势中可以长时间停留在高位或低位；零波幅窗口留空。',
  },
  cmf: {
    name: 'Chaikin 资金流',
    summary: (p) => studySummary('cmf', p),
    formula: (p) => `CMF${p.cmf_period} = Σ[(2C − H − L) / (H − L) × V] / ΣV`,
    text: '衡量收盘位置与成交量的关系，正负值不是实际净资金流入流出；平价K线的乘数取零。',
  },
  obv: { name: 'OBV 能量潮', summary: () => '累计成交量', formula: () => '收盘上涨加成交量，下跌减成交量，持平不变', text: '观察价格与量能是否同向，不比较不同载入区间的绝对数值；缺量后重新累计。' },
  atr: {
    name: 'ATR 波动率',
    summary: (p) => studySummary('atr', p),
    formula: (p) => `TR = max(H−L, |H−前收|, |L−前收|)；ATR% = Wilder ATR${p.atr_period} / C × 100`,
    text: '用于跨价格级别比较波动与估算风险距离，不代表涨跌方向；副图展示百分比而非美元。',
  },
  squeeze: {
    name: '波动收缩动量',
    summary: (p) => studySummary('squeeze', p),
    formula: (p) => `BB(${p.squeeze_bb_period},${formatParam(p.squeeze_bb_mult)}σ)位于KC(EMA${p.squeeze_kc_period},${formatParam(p.squeeze_kc_mult)}ATR)内为收缩；柱线为去中心价格的${p.squeeze_momentum_period}根回归端点`,
    text: '金色零轴点表示收缩，其余点表示非收缩；柱线表示动量而非收益预测。解除收缩不保证突破。',
  },
};
const TECH_PRESETS = {
  basic: { name: '经典', ma: true, macd: true, rsi: false, channel: 'bb', trend: 'none', study: 'none' },
  trend: { name: '趋势跟踪', ma: false, macd: false, rsi: false, channel: 'adaptive', trend: 'supertrend', study: 'adx' },
  breakout: { name: '区间突破', ma: false, macd: false, rsi: true, channel: 'donchian', trend: 'none', study: 'adx' },
  squeeze: { name: '波动收缩', ma: false, macd: false, rsi: false, channel: 'bb', trend: 'none', study: 'squeeze' },
  flow: { name: '量价确认', ma: false, macd: false, rsi: false, channel: 'vwap', trend: 'kama', study: 'cmf' },
  regression: { name: '回归结构', ma: false, macd: false, rsi: true, channel: 'regression', trend: 'none', study: 'none' },
};

function technicalGuide(params) {
  const group = (title, methods) => `<section><h4>${title}</h4><div class="technical-methods">${Object.entries(methods).filter(([key]) => key !== 'none').map(([, method]) => `<article><h5>${method.name}<span>${method.summary(params)}</span></h5><code>${esc(method.formula(params))}</code><p>${method.text}</p></article>`).join('')}</div></section>`;
  return `<details class="technical-guide">
    <summary>指标手册 <span>当前参数与计算口径</span></summary>
    <div class="technical-guide-body">
      <p>周期按实际 K 线根数计。指标只使用当前及以前的数据，预热不足留空；未收盘 K 线会随行情变化。</p>
      ${group('主图通道', CHANNELS)}${group('趋势叠加', TRENDS)}${group('高级副图', STUDIES)}
      <p>MA 为简单均线；RSI 使用 Wilder 平滑，完全横盘取 50；MACD 柱线为 2 ×（DIF − DEA）。递推指标会受载入历史长度影响。主图“价位”标记最近 180 根 K 线的局部摆动高低点，仅作结构参考，不是交易信号。</p>
      <div class="technical-references"><span>方法参考</span>
        <a href="https://ta-lib.org/" target="_blank" rel="noopener noreferrer">TA-Lib</a>
        <a href="https://technical-analysis-library-in-python.readthedocs.io/en/latest/ta.html" target="_blank" rel="noopener noreferrer">ta</a>
        <a href="https://python.stockindicators.dev/indicators/" target="_blank" rel="noopener noreferrer">Stock.Indicators</a>
        <a href="https://xgboosted.github.io/pandas-ta-classic/indicators.html" target="_blank" rel="noopener noreferrer">Pandas TA Classic</a>
        <a href="https://tulipindicators.org/" target="_blank" rel="noopener noreferrer">Tulip Indicators</a>
        <a href="https://www.backtrader.com/docu/indautoref/" target="_blank" rel="noopener noreferrer">Backtrader</a>
      </div>
    </div>
  </details>`;
}

const BASE_PARAM_FIELDS = [
  { key: 'macd_fast', label: 'MACD 快线' },
  { key: 'macd_slow', label: 'MACD 慢线' },
  { key: 'macd_signal', label: 'MACD 信号' },
  { key: 'rsi_period', label: 'RSI 周期' },
];

function paramField(field, params) {
  const range = PARAM_RANGES[field.key];
  return `<label class="studio-field">
    <span>${esc(field.label)}</span>
    <input class="studio-param-input" type="number" data-param="${field.key}" value="${formatParam(params[field.key])}" min="${range.min}" max="${range.max}" step="${range.step || 1}" inputmode="decimal" required>
  </label>`;
}

function paramSection(title, meta, fields, params) {
  if (!fields.length) return '';
  return `<section class="studio-param-section">
    <header><strong>${esc(title)}</strong><span>${esc(meta)}</span></header>
    <div class="studio-fields">${fields.map((field) => paramField(field, params)).join('')}</div>
  </section>`;
}

function studioModule({ group, label, methods, current, params, summary }) {
  const active = methods[current] || methods.none;
  const detail = summary(current, params) || '未启用';
  const options = Object.entries(methods).map(([key, method]) => {
    const optionDetail = method.summary ? method.summary(params) : '';
    return `<button type="button" class="studio-option ${key === current ? 'selected' : ''}" id="studio-option-${group}-${key}" data-tech-option="${group}" data-value="${key}" role="option" aria-selected="${key === current}">
      <span><strong>${esc(method.name)}</strong>${optionDetail ? `<small>${esc(optionDetail)}</small>` : ''}</span>
      <i>${ui.icon('check', 13)}</i>
    </button>`;
  }).join('');
  return `<div class="studio-module ${current === 'none' ? 'is-empty' : ''}" data-module="${group}">
    <button type="button" class="studio-trigger" data-menu-toggle="${group}" aria-haspopup="listbox" aria-controls="studio-menu-${group}" aria-expanded="false" title="${esc(`${label}：${active.name} · ${detail}`)}">
      <span class="studio-marker" aria-hidden="true"></span>
      <span class="studio-trigger-copy">
        <span class="studio-caption"><span class="studio-role">${esc(label)}</span><strong data-current-name="${group}">${esc(active.name)}</strong></span>
        <small data-current-meta="${group}">${esc(detail)}</small>
      </span>
      ${ui.icon('chevronDown', 13, 'studio-chevron')}
    </button>
    <div class="studio-menu" id="studio-menu-${group}" data-menu="${group}" role="listbox" aria-label="${esc(label)}" hidden>${options}</div>
  </div>`;
}

function paramSheet(params, { channel, trend, study }) {
  const periods = params.ma_periods.map((value, index) => `<label class="studio-field">
    <span>均线 ${index + 1}</span>
    <input class="studio-param-input" type="number" data-ma-index="${index}" value="${formatParam(value)}" min="2" max="300" step="1" inputmode="numeric" required>
  </label>`).join('');
  return `<div class="studio-param-head">
      <div><strong>指标参数</strong><span>调整后重新计算，当前缩放保持不变</span></div>
      <div class="studio-param-actions">
        <button type="button" class="btn small ghost" data-param-defaults>恢复默认</button>
        <button type="button" class="btn small" data-param-apply>应用参数</button>
      </div>
    </div>
    <div class="studio-param-grid">
      <section class="studio-param-section" data-section="base">
        <header><strong>基础指标</strong><span>均线 / MACD / RSI</span></header>
        <div class="studio-fields">${periods}${BASE_PARAM_FIELDS.map((field) => paramField(field, params)).join('')}</div>
      </section>
      ${paramSection(CHANNELS[channel]?.name || '主图通道', '主图叠加', CHANNEL_PARAMS[channel] || [], params)}
      ${paramSection(TRENDS[trend]?.name || '趋势叠加', '趋势线', TREND_PARAMS[trend] || [], params)}
      ${paramSection(STUDIES[study]?.name || '高级副图', '独立副图', STUDY_PARAMS[study] || [], params)}
    </div>
    <p class="studio-param-error" data-param-error hidden></p>`;
}

const ACTION_LABELS = {
  upgrade: '上调',
  downgrade: '下调',
  initiated: '首次覆盖',
  initiates: '首次覆盖',
  maintain: '维持',
  maintains: '维持',
  reiterated: '重申',
  reinitiated: '恢复覆盖',
};

function clampPercent(value) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.min(100, Math.max(0, number)) : 0;
}

function sourceLabel(source) {
  if (source === 'nasdaq') return 'Nasdaq';
  if (source === 'eastmoney_trends') return '东方财富';
  if (source === 'sec_edgar') return 'SEC EDGAR';
  return '东方财富';
}

function websiteHref(value) {
  const raw = String(value || '').trim();
  if (!raw) return '';
  if (/^https?:\/\//i.test(raw)) return raw;
  if (/^[\w.-]+\.[a-z]{2,}(\/.*)?$/i.test(raw)) return `https://${raw}`;
  return '';
}

function renderFinancials(rows, mode, currency, note) {
  if (!rows.length) {
    return {
      chart: ui.emptyState('暂无财务数据', '东方财富 F10 暂未返回可用财务指标。'),
      tiles: '',
      note: '',
    };
  }
  const latest = rows[0];
  const tile = (label, value, sub = '') => `
    <div class="metric-tile">
      <div class="mt-label">${esc(label)}</div>
      <div class="mt-value">${value}</div>
      ${sub ? `<div class="mt-label" style="margin-top:2px">${esc(sub)}</div>` : ''}
    </div>`;
  return {
    chart: '',
    tiles: `
      ${tile('营业收入', `${fmtCompact(latest.revenue)}`, latest.revenue_yoy !== null && latest.revenue_yoy !== undefined ? `同比 ${fmtPct(latest.revenue_yoy)}` : `${latest.date} · ${currency}`)}
      ${tile('净利润', `${fmtCompact(latest.net_profit)}`, latest.net_profit_yoy !== null && latest.net_profit_yoy !== undefined ? `同比 ${fmtPct(latest.net_profit_yoy)}` : mode === 'annual' ? '年报' : '单季报')}
      ${tile('毛利率', latest.gross_margin !== null && latest.gross_margin !== undefined ? fmtPct(latest.gross_margin, 1, false) : '—', '盈利质量')}
      ${tile('ROE', latest.roe !== null && latest.roe !== undefined ? fmtPct(latest.roe, 1, false) : latest.net_margin !== null && latest.net_margin !== undefined ? fmtPct(latest.net_margin, 1, false) : '—', '净资产回报')}`,
    note: note || '',
  };
}

function analystBlock(analyst, surprises) {
  if (!analyst && !(surprises || []).length) {
    return ui.emptyState('暂无分析师数据', 'Nasdaq 未返回评级或盈利惊喜数据。');
  }
  const changes = (analyst?.changes || [])
    .map((item) => {
      const action = ACTION_LABELS[String(item.action || '').toLowerCase()] || item.action || '调整';
      const from = item.from ? `${esc(item.from)} → ` : '';
      return `<tr>
        <td>${esc(fmtDate(item.date, 'short'))}</td>
        <td>${esc(item.firm || '—')}</td>
        <td>${esc(action)}</td>
        <td>${from}${esc(item.to || '—')}</td>
      </tr>`;
    })
    .join('');
  const surpriseRows = (surprises || [])
    .slice(0, 6)
    .map(
      (item) => `<tr>
        <td>${esc(item.quarter || '—')}</td>
        <td>${fmtNum(item.eps, 2)}</td>
        <td>${fmtNum(item.consensus, 2)}</td>
        <td class="${tone(item.surprise_pct)}">${fmtPct(item.surprise_pct)}</td>
      </tr>`,
    )
    .join('');
  return `
    <div class="analyst-rating">
      <div class="rating-badge">${esc(analyst?.mean_rating || analyst?.summary || '—')}</div>
      <div class="analyst-meta">
        <b>${analyst?.analyst_count ? `${fmtInt(analyst.analyst_count)} 家机构覆盖` : '机构覆盖数据有限'}</b><br>
        ${esc(typeof analyst?.summary === 'string' ? analyst.summary : 'Nasdaq 分析师评级汇总')}
      </div>
    </div>
    <div class="field-label" style="margin:8px 0 2px">近期评级变动</div>
    ${
      changes
        ? `<table class="mini-table"><thead><tr><th>日期</th><th>机构</th><th>动作</th><th>评级</th></tr></thead><tbody>${changes}</tbody></table>`
        : '<p class="field-hint">暂无近期评级变动记录。</p>'
    }
    <div class="field-label" style="margin:14px 0 2px">盈利惊喜</div>
    ${
      surpriseRows
        ? `<table class="mini-table"><thead><tr><th>季度</th><th>EPS</th><th>预期</th><th>惊喜</th></tr></thead><tbody>${surpriseRows}</tbody></table>`
        : '<p class="field-hint">暂无盈利惊喜数据。</p>'
    }`;
}

function profileBlock(profile) {
  if (!profile) {
    return ui.emptyState('暂无公司资料', '该公司可能为 ETF，或东方财富 F10 暂无收录。');
  }
  const website = websiteHref(profile.website);
  const facts = [
    ['英文名称', profile.name_en],
    ['所属行业', profile.industry],
    ['成立日期', profile.founded],
    ['员工人数', profile.employees ? fmtInt(profile.employees) : ''],
    ['注册地', profile.location],
    ['董事长', profile.chairman],
    ['财年截止', profile.fiscal_year_end],
    ['ISIN', profile.isin],
  ].filter(([, value]) => value);
  return `
    <div class="profile-description" data-profile-desc>${esc(profile.description || '暂无公司简介。')}</div>
    ${profile.description && profile.description.length > 120 ? `<button class="btn ghost small" type="button" data-expand-profile style="margin-top:8px">展开全文</button>` : ''}
    <div class="profile-grid">
      ${facts.map(([label, value]) => `<div class="profile-fact"><span class="pf-label">${esc(label)}</span><span class="pf-value" title="${esc(value)}">${esc(value)}</span></div>`).join('')}
      ${website ? `<div class="profile-fact"><span class="pf-label">官网</span><span class="pf-value"><a href="${esc(website)}" target="_blank" rel="noopener noreferrer">${esc(profile.website)}</a></span></div>` : ''}
    </div>`;
}

function peersBlock(peers) {
  if (!peers?.length) {
    return ui.emptyState('暂无同业样本', '行业分类缺失或全市场快照暂不可用。');
  }
  return `
    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>标的</th><th>价格</th><th>涨跌</th><th>PE</th><th>PB</th><th>总市值</th><th>年内</th></tr></thead>
        <tbody>
          ${peers
            .map(
              (item) => `<tr class="clickable" data-symbol="${esc(item.symbol)}">
                <td><div class="sym-cell"><div><div class="sym">${esc(item.symbol)}</div><div class="nm">${esc(item.name || '')}</div></div></div></td>
                <td class="num-cell">${fmtPrice(item.price)}</td>
                <td class="${tone(item.change_pct)}">${fmtPct(item.change_pct)}</td>
                <td>${fmtNum(item.pe, 2)}</td>
                <td>${fmtNum(item.pb, 2)}</td>
                <td>${fmtCompact(item.market_cap)}</td>
                <td class="${tone(item.chg_ytd)}">${fmtPct(item.chg_ytd)}</td>
              </tr>`,
            )
            .join('')}
        </tbody>
      </table>
    </div>`;
}

const FILING_LABELS = {
  '3': '初始持股申报', '4': '持股变动', '5': '年度持股变动', '144': '拟出售证券',
  '8-K': '重大事项', '8-K/A': '重大事项（修订）',
  '10-K': '年度报告', '10-K/A': '年度报告（修订）',
  '10-Q': '季度报告', '10-Q/A': '季度报告（修订）',
  '20-F': '外国发行人年报', '20-F/A': '外国发行人年报（修订）',
  '40-F': '加拿大发行人年报', '40-F/A': '加拿大发行人年报（修订）',
  '6-K': '外国发行人临时报告', '6-K/A': '外国发行人临时报告（修订）',
  'DEF 14A': '股东大会委托书', 'DEF 14A/A': '股东大会委托书（修订）', 'PRE 14A': '股东大会委托书（预备）',
  'SC 13G': '机构持股', 'SC 13G/A': '机构持股（修订）',
  'SC 13D': '主动持股', 'SC 13D/A': '主动持股（修订）',
  'SCHEDULE 13G': '机构持股', 'SCHEDULE 13G/A': '机构持股（修订）',
  'SCHEDULE 13D': '主动持股', 'SCHEDULE 13D/A': '主动持股（修订）',
  'DEFA14A': '股东大会委托书（补充）', 'SD': '冲突矿产披露',
  'S-1': '注册声明', 'S-1/A': '注册声明（修订）',
  'S-3': '储架注册', 'S-3/A': '储架注册（修订）',
  '424B2': '证券发行说明书', '424B3': '证券发行说明书', '424B5': '证券发行说明书',
  'FWP': '自由撰写招股书', '425': '并购沟通文件', '497K': '基金摘要说明书',
};

function filingsBlock(filings) {
  const items = filings?.items || [];
  if (!items.length) return ui.emptyState('暂无 SEC 申报', '未找到该公司的 EDGAR 申报记录。');
  return `
    <div class="filings-list">
      ${items
        .map((item) => {
          const href = safeUrl(item.url) || safeUrl(item.index_url);
          const form = String(item.form || '').trim();
          const rawDescription = String(item.description || '').trim();
          const generic = !rawDescription || rawDescription.toLowerCase() === form.toLowerCase() || rawDescription.toLowerCase().startsWith('form ');
          const description = generic ? (FILING_LABELS[form] || 'SEC 申报') : rawDescription;
          const content = `
            <span class="filing-form">FORM ${esc(form || '—')}</span>
            <span class="filing-date">${esc(fmtDate(item.date))}</span>
            <span class="filing-desc" title="${esc(description)}">${esc(description)}</span>
            ${ui.icon('external', 12)}`;
          return href
            ? `<a class="filing-row" href="${esc(href)}" target="_blank" rel="noopener noreferrer">${content}</a>`
            : `<div class="filing-row">${content}</div>`;
        })
        .join('')}
    </div>`;
}

function dividendsBlock(dividends) {
  if (!dividends || (!dividends.history?.length && !dividends.yield_pct && !dividends.annual_dividend)) {
    return ui.emptyState('暂无股息记录', '该公司当前可能不派息，或数据源暂无收录。');
  }
  const tile = (label, value) => `<div class="metric-tile"><div class="mt-label">${esc(label)}</div><div class="mt-value">${value}</div></div>`;
  return `
    <div class="fin-tiles" style="margin-top:0">
      ${tile('股息率', dividends.yield_pct !== null && dividends.yield_pct !== undefined ? fmtPct(dividends.yield_pct, 2, false) : '—')}
      ${tile('年化派息', dividends.annual_dividend !== null && dividends.annual_dividend !== undefined ? fmtMoney(dividends.annual_dividend) : '—')}
      ${tile('派息率', dividends.payout_ratio !== null && dividends.payout_ratio !== undefined ? fmtPct(dividends.payout_ratio, 1, false) : '—')}
      ${tile('最近除息', dividends.ex_date ? fmtDate(dividends.ex_date) : '—')}
    </div>
    ${
      dividends.history?.length
        ? `<table class="mini-table" style="margin-top:12px"><thead><tr><th>除息日</th><th>金额</th><th>类型</th><th>支付日</th></tr></thead><tbody>
            ${dividends.history
              .slice(0, 6)
              .map(
                (item) => `<tr>
                  <td>${esc(fmtDate(item.ex_date))}</td>
                  <td>${item.amount !== null && item.amount !== undefined ? fmtMoney(item.amount) : '—'}</td>
                  <td>${esc(item.type || '—')}</td>
                  <td>${esc(fmtDate(item.payment_date))}</td>
                </tr>`,
              )
              .join('')}
          </tbody></table>`
        : ''
    }`;
}

function secTile(label, value, sub = '') {
  return `<div class="metric-tile"><div class="mt-label">${esc(label)}</div><div class="mt-value">${value}</div>${sub ? `<div class="mt-label" style="margin-top:2px">${esc(sub)}</div>` : ''}</div>`;
}

function renderSecTiles(ratios, rows) {
  const latest = (ratios || [])[ratios.length - 1] || {};
  const latestRow = (rows || [])[rows.length - 1] || {};
  const pct = (value, digits = 1) => (Number.isFinite(Number(value)) && value !== null ? fmtPct(value, digits, false) : '—');
  const num = (value, digits = 2) => (Number.isFinite(Number(value)) && value !== null ? fmtNum(value, digits) : '—');
  const days = (value) => (Number.isFinite(Number(value)) && value !== null ? `${fmtNum(value, 0)} 天` : '—');
  return [
    secTile('毛利率', pct(latest.gross_margin)),
    secTile('营业利润率', pct(latest.operating_margin)),
    secTile('净利率', pct(latest.net_margin)),
    secTile('FCF 利润率', pct(latest.fcf_margin)),
    secTile('ROE', pct(latest.roe), '平均权益口径'),
    secTile('ROIC', pct(latest.roic), 'NOPAT / 投入资本'),
    secTile('现金转换周期', days(latest.ccc), `应收 ${num(latest.dso, 0)} · 存货 ${num(latest.dio, 0)} · 应付 ${num(latest.dpo, 0)}`),
    secTile('应计比率', latest.accrual_ratio !== null && latest.accrual_ratio !== undefined ? `${Number(latest.accrual_ratio).toFixed(1)}%` : '—', '越低越好'),
    secTile('流动比率', num(latest.current_ratio)),
    secTile('杠杆率', pct(latest.debt_to_assets), latestRow.date ? `截至 ${latestRow.date}` : '负债 / 总资产'),
    secTile('有效税率', pct(latest.effective_tax_rate), '税前利润口径'),
    secTile('Rule of 40', latest.rule_of_40 !== null && latest.rule_of_40 !== undefined ? `${Number(latest.rule_of_40) >= 0 ? '+' : ''}${fmtNum(latest.rule_of_40, 1)}` : '—', '营收增速 + FCF 利润率'),
  ].join('');
}

function renderSecFacts(payload, mode) {
  if (mode !== 'annual') return '';
  const trend = payload.trend;
  const alloc = payload.capital_allocation;
  if (!trend && !alloc) return '';
  const chips = [];
  const push = (label, value, tone = '') => chips.push({ label, value, tone });
  const signed = (value, digits = 1) =>
    Number.isFinite(Number(value)) && value !== null ? `${Number(value) >= 0 ? '+' : ''}${fmtNum(value, digits)}` : '—';
  const cagr = (value) => (Number.isFinite(Number(value)) && value !== null ? `${signed(value)}%` : '—');
  if (trend) {
    push(`营收 CAGR · ${trend.years}Y`, cagr(trend.revenue_cagr), trend.revenue_cagr >= 0 ? 'pos' : 'neg');
    push('FCF CAGR', cagr(trend.fcf_cagr), trend.fcf_cagr >= 0 ? 'pos' : 'neg');
    push('毛利率变化', trend.gross_margin_change !== null ? `${signed(trend.gross_margin_change)}pct` : '—', trend.gross_margin_change >= 0 ? 'pos' : 'neg');
    push('ROIC 变化', trend.roic_change !== null ? `${signed(trend.roic_change)}pct` : '—', trend.roic_change >= 0 ? 'pos' : 'neg');
    push('FCF 为正年份', `${trend.fcf_positive_years}/${trend.window}`);
  }
  if (alloc?.latest) {
    const latest = alloc.latest;
    const payout = latest.payout_of_fcf;
    push('分红+回购 / FCF', payout !== null && payout !== undefined ? `${fmtNum(payout, 0)}%` : '—', payout > 100 ? 'neg' : 'pos');
    push('资本开支 / OCF', latest.capex_of_ocf !== null && latest.capex_of_ocf !== undefined ? `${fmtNum(latest.capex_of_ocf, 0)}%` : '—');
    push(
      '留存现金',
      latest.retained !== null && latest.retained !== undefined ? fmtMoneyCompact(latest.retained) : '—',
      latest.retained == null ? '' : latest.retained >= 0 ? 'pos' : 'neg',
    );
    if (alloc.three_year) {
      const total = alloc.three_year;
      push(`近 ${total.years} 年股东回报`, fmtMoneyCompact(total.returned || 0));
    }
  }
  if (!chips.length) return '';
  return `<div class="sec-facts">
    <span class="sec-facts-label">${ui.icon('trendUp', 12)}趋势与资本配置</span>
    <div class="sec-facts-chips">
      ${chips
        .map(
          (chip) => `<span class="sec-fact"><span>${esc(chip.label)}</span><b class="${esc(chip.tone || '')}">${esc(chip.value)}</b></span>`,
        )
        .join('')}
    </div>
  </div>`;
}

function renderSecInsights(insights) {
  const list = (insights || [])
    .map((item) => `<div class="sec-insight ${esc(item.tone || 'neutral')}"><span class="si-dot"></span><span>${esc(item.text)}</span></div>`)
    .join('');
  return list ? `<div class="insight-block sec-insights"><h4>${ui.icon('check', 12)}深度解读</h4><div class="si-list">${list}</div></div>` : '';
}

export async function mount(root, params, ctx) {
  const symbol = String(params.symbol || '').toUpperCase();
  const { signal, isActive, navigate } = ctx;
  const chartPrefs = store.chartPrefs();
  chartPrefs.params = store.chartParams();
  const chartParamsQuery = () => {
    const custom = {};
    Object.entries(chartPrefs.params).forEach(([key, value]) => {
      if (JSON.stringify(value) !== JSON.stringify(DEFAULT_INDICATOR_PARAMS[key])) custom[key] = value;
    });
    return Object.keys(custom).length ? encodeURIComponent(JSON.stringify(custom)) : '';
  };
  const overviewParams = chartParamsQuery();
  let data;
  try {
    data = await api.get(`/api/stocks/${encodeURIComponent(symbol)}/overview${overviewParams ? `?params=${overviewParams}` : ''}`, {
      signal,
      timeout: 120000,
    });
  } catch (error) {
    if (error?.name === 'AbortError') return undefined;
    root.innerHTML = `
      <section class="view">
        ${viewHead({ eyebrow: 'EQUITY RESEARCH', title: symbol, sub: '未能获取该标的的研究数据。' })}
        <div class="panel">${ui.errorPanel(error.message || '个股数据加载失败')}</div>
      </section>`;
    ui.bindRetry(root, () => ctx.reload());
    return undefined;
  }
  if (!isActive()) return undefined;

  const quote = data.quote || {};
  const profile = data.profile;
  const score = data.score || {};
  const financials = data.financials || { annual: [], quarterly: [] };
  const technical = score.technical || {};
  const price = quote.price ?? technical.last;
  const change = quote.change;
  const changePct = quote.change_pct;
  const low = quote.week52_low;
  const high = quote.week52_high;
  const rangePosition =
    low !== null && low !== undefined && high !== null && high !== undefined && high > low && price !== null && price !== undefined
      ? clampPercent(((Number(price) - Number(low)) / (Number(high) - Number(low))) * 100)
      : null;
  const industry = quote.industry || profile?.industry || score.metrics?.industry || '';
  const watched = store.isWatched(symbol);
  const name = quote.name && quote.name !== symbol ? quote.name : '';
  const subParts = [
    profile?.employees ? `员工 ${fmtInt(profile.employees)}` : '',
    profile?.founded ? `成立于 ${profile.founded}` : '',
  ].filter(Boolean);
  const dividendSub = data.dividends?.annual_dividend !== null && data.dividends?.annual_dividend !== undefined
    ? `年化派息 ${fmtMoney(data.dividends.annual_dividend)}`
    : data.dividends?.ex_date
      ? `最近除息 ${fmtDate(data.dividends.ex_date)}`
      : quote.dividend_yield !== null && quote.dividend_yield !== undefined
        ? '股息率来自行情快照'
        : '暂无派息记录';

  const priceStats = `
    <div class="stat-strip stock-stats">
      ${statCard({
        label: '总市值',
        value: `${fmtCompact(quote.market_cap)}<small>美元</small>`,
        sub: quote.float_cap ? `流通 ${fmtCompact(quote.float_cap)}` : '全市场快照口径',
      })}
      ${statCard({
        label: '市盈率 TTM',
        value: fmtNum(score.metrics?.pe ?? quote.pe, 2),
        sub: score.metrics?.sector_pe ? `行业 PE ${fmtNum(score.metrics.sector_pe, 2)}` : '行业样本不足',
      })}
      ${statCard({
        label: '市净率',
        value: fmtNum(score.metrics?.pb ?? quote.pb, 2),
        sub: score.metrics?.sector_pb ? `行业 PB ${fmtNum(score.metrics.sector_pb, 2)}` : '行业样本不足',
      })}
      ${statCard({
        label: '股息率',
        value: quote.dividend_yield !== null && quote.dividend_yield !== undefined ? `${fmtNum(quote.dividend_yield, 2)}<small>%</small>` : '—',
        sub: dividendSub,
      })}
      ${statCard({
        label: '今日振幅',
        value: quote.amplitude !== null && quote.amplitude !== undefined ? `${fmtNum(quote.amplitude, 2)}<small>%</small>` : '—',
        sub: quote.turnover !== null && quote.turnover !== undefined ? `换手率 ${fmtNum(quote.turnover, 2)}%` : `成交量 ${fmtCompact(quote.volume)} 股`,
      })}
      <div class="stat-card">
        <div class="stat-label"><span>52 周区间</span><span class="mono">${rangePosition !== null ? `${rangePosition.toFixed(0)}%` : ''}</span></div>
        <div class="stat-value" style="font-size:14.5px">${fmtPrice(low)} – ${fmtPrice(high)}</div>
        <div class="week-range">
          <div class="week-track">${rangePosition !== null ? `<span class="week-marker" style="left:${rangePosition}%"></span>` : ''}</div>
          <div class="week-labels"><span>${fmtPrice(low)}</span><span>${fmtPrice(high)}</span></div>
        </div>
      </div>
    </div>`;

  const initialFinancialMode = financials.annual?.length ? 'annual' : 'quarterly';
  const initialFinancialRows = initialFinancialMode === 'annual' ? financials.annual || [] : financials.quarterly || [];
  const financialView = renderFinancials(initialFinancialRows, initialFinancialMode, financials.currency || 'USD', financials.note);

  root.innerHTML = `
    <section class="view">
      ${ui.warnBanner(data.warnings || [])}
      <div class="stock-head">
        <div class="stock-head-top">
          <div class="stock-id">
            <div class="stock-title-line">
              <h1>${esc(symbol)}</h1>
              ${name ? `<span class="stock-cn-name">${esc(name)}</span>` : ''}
              <span class="badge">${esc(quote.exchange || 'US')}</span>
              <span class="pill info">${esc(quote.kind || '股票')}</span>
              ${industry ? `<span class="pill tone-neutral">${esc(industry)}</span>` : ''}
            </div>
            <div class="stock-sub">
              ${subParts.map((part) => `<span>${esc(part)}</span>`).join('<span class="sep"></span>')}
              ${data.as_of ? `${subParts.length ? '<span class="sep"></span>' : ''}<span>更新于 ${esc(fmtDate(data.as_of, 'full'))}</span>` : ''}
            </div>
          </div>
          <div class="stock-actions">
            <button class="star-btn stock-action ${watched ? 'on' : ''}" type="button" data-star aria-label="${watched ? '已自选' : '加入自选'}" title="${watched ? '已自选' : '加入自选'}">
              ${ui.starIcon(watched, 14)}<span class="action-label">${watched ? '已自选' : '加入自选'}</span>
            </button>
            <a class="btn small stock-action" href="#/compare?symbols=${encodeURIComponent(symbol)}" aria-label="加入对比" title="加入对比">${ui.icon('compare', 14)}<span class="action-label">加入对比</span></a>
          </div>
        </div>
        <div class="stock-quote">
          <div class="quote-primary">
            <span class="price-big">${fmtPrice(price)}</span>
            <span class="price-currency">USD</span>
            <span class="quote-change ${tone(changePct)}">${fmtPct(changePct)}</span>
            <span class="quote-change ${tone(change)}">${change !== null && change !== undefined ? `${change > 0 ? '+' : ''}${fmtNum(change, 2)}` : '—'}</span>
          </div>
          <dl class="quote-session">
            <div><dt>开盘</dt><dd>${fmtPrice(quote.open)}</dd></div>
            <div><dt>最高</dt><dd>${fmtPrice(quote.high)}</dd></div>
            <div><dt>最低</dt><dd>${fmtPrice(quote.low)}</dd></div>
            <div><dt>成交量</dt><dd>${fmtCompact(quote.volume)}</dd></div>
          </dl>
        </div>
      </div>

      ${priceStats}

      <div class="stock-main-grid">
        <section class="panel technical-panel">
          <div class="panel-head">
            <div class="panel-title">技术分析 <span class="sub">价格结构 · 趋势强度 · 量价关系</span></div>
            <div class="panel-actions" data-range-buttons title="快捷键 1–9 / 0 依次切换 1D–MAX">
              <div class="seg">
                ${RANGES.map((range) => `<button type="button" data-range="${range}" class="${range === '1Y' ? 'active' : ''}">${range}</button>`).join('')}
              </div>
            </div>
          </div>
          <div class="studio">
            <div class="studio-bar">
              <div class="studio-presets" role="group" aria-label="技术分析视角">
                <span class="studio-role">视角</span>
                ${Object.entries(TECH_PRESETS).map(([key, preset]) => `<button type="button" class="studio-preset" data-tech-preset="${key}">${preset.name}</button>`).join('')}
              </div>
              <div class="studio-tools">
                <button type="button" class="studio-tool" data-param-toggle aria-expanded="false" aria-controls="studio-param-sheet" title="调整指标周期与倍数">${ui.icon('sliders', 14)}<span>参数</span></button>
                <button type="button" class="studio-tool" data-chart-reset title="恢复完整可见区间" aria-label="重置缩放">${ui.icon('refresh', 14)}</button>
                <button type="button" class="studio-tool" data-chart-export title="导出当前图表 PNG" aria-label="导出图片">${ui.icon('download', 14)}</button>
              </div>
            </div>
            <div class="studio-modules">
              <div class="studio-picker" role="group" aria-label="主图通道、趋势叠加与副图设置">
                ${studioModule({ group: 'channel', label: '主图', methods: CHANNELS, current: chartPrefs.channel, params: chartPrefs.params, summary: channelSummary })}
                ${studioModule({ group: 'trend', label: '趋势', methods: TRENDS, current: chartPrefs.trend, params: chartPrefs.params, summary: trendSummary })}
                ${studioModule({ group: 'study', label: '副图', methods: STUDIES, current: chartPrefs.study, params: chartPrefs.params, summary: studySummary })}
              </div>
              <div class="studio-basics">
                <span class="studio-role">基础</span>
                <div class="studio-switches" role="group" aria-label="基础指标和显示">
                  <button type="button" class="chart-toggle" data-chart-toggle="ma" title="叠加所选周期的简单均线">MA</button>
                  <button type="button" class="chart-toggle" data-chart-toggle="macd" title="MACD 副图">MACD</button>
                  <button type="button" class="chart-toggle" data-chart-toggle="rsi" title="RSI 副图">RSI</button>
                  <button type="button" class="chart-toggle" data-chart-toggle="levels" title="最近波段的支撑与压力">价位</button>
                  <button type="button" class="chart-toggle" data-chart-toggle="log" title="对数价格刻度">对数</button>
                </div>
              </div>
            </div>
            <div class="studio-param-sheet" id="studio-param-sheet" data-param-sheet hidden>
              ${paramSheet(chartPrefs.params, chartPrefs)}
            </div>
          </div>
          <div class="chart-toolbar"><div class="chart-legend" data-chart-legend><span class="cl-date">—</span></div></div>
          <div class="chart-body"><div class="chart" data-candles role="img" aria-label="价格、成交量与技术指标联动图" style="height:450px"></div></div>
          <div class="chart-meta" data-chart-meta>正在加载 1Y 行情…</div>
          <div class="technical-caption" data-tech-caption></div>
          <div class="technical-readout" data-tech-readout aria-label="最近一根K线的技术状态"></div>
          ${technicalGuide(chartPrefs.params)}
        </section>
      </div>

      <div class="fundamentals-grid">
        <section class="panel">
          <div class="panel-head">
            <div class="panel-title">财务概览 <span class="tag">${esc((financials.source || 'EASTMONEY F10').toUpperCase())}</span></div>
            <div class="panel-actions">
              <div class="seg" data-fin-mode>
                <button type="button" data-mode="annual" class="${initialFinancialMode === 'annual' ? 'active' : ''}">年报</button>
                <button type="button" data-mode="quarterly" class="${initialFinancialMode === 'quarterly' ? 'active' : ''}">单季</button>
              </div>
            </div>
          </div>
          <div class="panel-body tight">
            <div class="chart" data-fin-chart style="height:286px">${financialView.chart}</div>
            <div class="fin-tiles" data-fin-tiles>${financialView.tiles}</div>
            <div class="field-hint" data-fin-note style="margin-top:9px">${esc(financialView.note || '数据来自东方财富 F10，单位为美元。')}</div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div class="panel-title">现金流质量 <span class="tag">SEC 10-K</span></div>
          </div>
          <div class="chart-meta" data-cashflow-meta>正在读取 SEC XBRL 数据…</div>
          <div class="panel-body tight"><div class="chart" data-cashflow style="height:286px"></div></div>
        </section>
      </div>

      <section class="panel section-gap" data-sec-panel>
        <div class="panel-head">
          <div class="panel-title">SEC 财报深读 <span class="tag">XBRL · COMPANYFACTS</span></div>
          <div class="panel-actions">
            <div class="seg" data-sec-mode>
              <button type="button" data-smode="annual" class="active">年报</button>
              <button type="button" data-smode="quarterly">单季</button>
            </div>
          </div>
        </div>
        <div class="chart-meta" data-sec-meta>正在读取 SEC XBRL 财务数据…</div>
        <div class="panel-body tight">
          <div class="sec-chart-col">
            <div class="chart" data-sec-chart style="height:272px"></div>
            <div class="metric-tiles sec-tiles" data-sec-tiles></div>
          </div>
          <div data-sec-facts></div>
          <div data-sec-insights></div>
        </div>
      </section>

      <section class="panel section-gap" data-mda-panel>
        <div class="panel-head">
          <div class="panel-title">MD&amp;A 文本洞察 <span class="tag">EDGAR NLP</span></div>
          <div class="panel-actions">
            <div class="seg" data-mda-mode>
              <button type="button" data-mmode="annual" class="active">年报 MD&amp;A</button>
              <button type="button" data-mmode="quarterly">最新 10-Q</button>
            </div>
          </div>
        </div>
        <div class="panel-body" data-mda-body>
          <div class="mda-loading"><span class="spinner" style="width:12px;height:12px;border-width:1.5px"></span><span>正在解析 SEC 原文，首次加载约 5–10 秒…</span></div>
        </div>
      </section>

      <div class="detail-grid section-gap">
        <section class="panel">
          <div class="panel-head"><div class="panel-title">分析师观点 <span class="tag">NASDAQ</span></div></div>
          <div class="panel-body">${analystBlock(data.analyst, data.earnings_surprise)}</div>
        </section>
        <section class="panel">
          <div class="panel-head"><div class="panel-title">公司资料 <span class="tag">F10</span></div></div>
          <div class="panel-body">${profileBlock(profile)}</div>
        </section>
      </div>

      <section class="panel section-gap">
        <div class="panel-head">
          <div class="panel-title">同业对比 <span class="sub">${esc(industry || '行业')} · 按市值</span></div>
          <div class="panel-actions"><a class="btn small ghost" href="#/compare?symbols=${encodeURIComponent([symbol, ...(data.peers || []).slice(0, 3).map((item) => item.symbol)].join(','))}">多股对比</a></div>
        </div>
        <div class="panel-body flush">${peersBlock(data.peers)}</div>
      </section>

      <div class="detail-grid section-gap">
        <section class="panel">
          <div class="panel-head"><div class="panel-title">SEC 申报 <span class="tag">EDGAR</span></div></div>
          <div class="panel-body">${filingsBlock(data.filings)}</div>
        </section>
        <section class="panel">
          <div class="panel-head"><div class="panel-title">股息与派息 <span class="tag">NASDAQ</span></div></div>
          <div class="panel-body">${dividendsBlock(data.dividends)}</div>
        </section>
      </div>

      <section class="panel section-gap">
        <div class="panel-head">
          <div class="panel-title">个股新闻 <span class="sub">东方财富资讯</span></div>
          <div class="panel-actions"><a class="btn small ghost" href="#/overview">市场快讯</a></div>
        </div>
        <div class="panel-body">
          ${
            data.news?.length
              ? `<div class="news-list">${data.news
                  .slice(0, 8)
                  .map(
                    (item) => `<article class="news-item">
                      <div class="news-time">${esc(fmtDate(item.date, 'short'))}</div>
                      <div class="news-main">
                        ${safeUrl(item.url) ? `<a class="news-title" href="${esc(safeUrl(item.url))}" target="_blank" rel="noopener noreferrer">${esc(item.title)}</a>` : `<span class="news-title">${esc(item.title)}</span>`}
                        ${item.summary ? `<p class="news-summary">${esc(item.summary)}</p>` : ''}
                        <div class="news-meta"><span class="src">${esc(item.media || '东方财富')}</span></div>
                      </div>
                    </article>`,
                  )
                  .join('')}</div>`
              : ui.emptyState('暂无个股新闻', '当前标的没有搜到相关资讯。')
          }
        </div>
      </section>
    </section>`;

  let financialMode = initialFinancialMode;
  let secMode = 'annual';
  let mdaMode = 'annual';
  let secPayload = null;
  let mdaPayload = null;
  let chartToken = 0;
  let disposed = false;
  const chartEl = $('[data-candles]', root);
  const chartMeta = $('[data-chart-meta]', root);
  const chartLegend = $('[data-chart-legend]', root);
  let chartPayload = null;
  let chartRange = '1Y';
  let chartIntraday = false;
  let chartBusy = false;
  let chartZoom = null;

  function paintStar() {
    const button = $('[data-star]', root);
    if (!button) return;
    const on = store.isWatched(symbol);
    button.classList.toggle('on', on);
    button.setAttribute('aria-label', on ? '已自选' : '加入自选');
    button.title = on ? '已自选' : '加入自选';
    button.innerHTML = `${ui.starIcon(on, 14)}<span class="action-label">${on ? '已自选' : '加入自选'}</span>`;
  }

  const methodGroups = { channel: CHANNELS, trend: TRENDS, study: STUDIES };
  const methodSummary = { channel: channelSummary, trend: trendSummary, study: studySummary };

  function paintStudioModules() {
    Object.entries(methodGroups).forEach(([group, methods]) => {
      const active = methods[chartPrefs[group]] || methods.none;
      const detail = methodSummary[group](chartPrefs[group], chartPrefs.params) || '未启用';
      const name = $(`[data-current-name="${group}"]`, root);
      const meta = $(`[data-current-meta="${group}"]`, root);
      const moduleEl = $(`.studio-module[data-module="${group}"]`, root);
      const trigger = $(`[data-menu-toggle="${group}"]`, root);
      if (name) name.textContent = active.name;
      if (meta) meta.textContent = detail;
      moduleEl?.classList.toggle('is-empty', chartPrefs[group] === 'none');
      if (trigger) trigger.title = `${trigger.querySelector('.studio-role')?.textContent || ''}：${active.name} · ${detail}`;
      $$(`[data-menu="${group}"] [data-tech-option]`, menuLayer).forEach((option) => {
        const selected = option.dataset.value === chartPrefs[group];
        option.classList.toggle('selected', selected);
        option.setAttribute('aria-selected', String(selected));
      });
    });
  }

  function paintChartToggles() {
    const unavailable = !chartPayload || chartIntraday || chartBusy;
    $$('[data-chart-toggle]', root).forEach((button) => {
      const key = button.dataset.chartToggle;
      const active = !chartIntraday && Boolean(chartPrefs[key]);
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', String(active));
      button.disabled = unavailable;
    });
    $$('[data-tech-preset]', root).forEach((button) => {
      const preset = TECH_PRESETS[button.dataset.techPreset];
      const active = !chartIntraday && Object.entries(preset).every(([key, value]) => key === 'name' || chartPrefs[key] === value);
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', String(active));
      button.disabled = unavailable;
    });
    $$('[data-menu-toggle]', root).forEach((button) => { button.disabled = unavailable; });
    $('[data-chart-reset]', root).disabled = unavailable;
    $('[data-chart-export]', root).disabled = !chartPayload || chartBusy;
    paintStudioModules();
  }

  function paintTechnicalReadout() {
    const holder = $('[data-tech-readout]', root);
    const caption = $('[data-tech-caption]', root);
    holder.hidden = !chartPayload || chartIntraday;
    caption.hidden = !chartPayload || chartIntraday;
    if (holder.hidden) return;
    const indicators = chartPayload.indicators || {};
    const activeParams = chartPayload.indicator_params || chartPrefs.params;
    const index = chartPayload.bars.length - 1;
    const at = (values) => isNum(values?.[index]) ? Number(values[index]) : null;
    const close = isNum(chartPayload.bars[index].c) ? Number(chartPayload.bars[index].c) : null;
    const band = indicators[chartPrefs.channel] || {};
    const lower = at(band.lower);
    const upper = at(band.upper);
    const position = close !== null && upper !== null && lower !== null && upper > lower ? (close - lower) / (upper - lower) * 100 : null;
    const adx = at(indicators.adx?.adx);
    const plus = at(indicators.adx?.plus_di);
    const minus = at(indicators.adx?.minus_di);
    const atr = at(indicators.atr_pct);
    const flow = at(indicators[`cmf${activeParams.cmf_period}`]);
    const squeeze = at(indicators.squeeze?.on);
    const previousSqueeze = indicators.squeeze?.on?.[index - 1];
    const trendText = adx === null ? '历史不足' : adx < 20 ? '方向性较弱' : plus > minus ? '+DI 上行占优' : plus < minus ? '−DI 下行占优' : '方向均衡';
    const methods = [CHANNELS[chartPrefs.channel], TRENDS[chartPrefs.trend], STUDIES[chartPrefs.study]].filter((method) => method.formula);
    caption.innerHTML = `<span>最新状态 <b>${esc(chartPayload.bars[index].t)}</b></span>` + methods.map((method) => `<span>${esc(method.name)} <b>${esc(method.summary(activeParams))}</b></span>`).join('');
    const tile = (label, value, sub, extra = '') => `<div class="technical-stat"><span>${label}</span><strong>${value}</strong><small>${sub}</small>${extra}</div>`;
    holder.innerHTML =
      tile(`趋势强度 · ADX${activeParams.adx_period}`, adx === null ? '—' : fmtNum(adx, 1), trendText) +
      tile(`通道位置 · ${esc(CHANNELS[chartPrefs.channel].name)}`, position === null ? '—' : `${fmtNum(position, 1)}<em>%</em>`, upper !== null && lower !== null ? `${fmtPrice(lower)} — ${fmtPrice(upper)}` : '选择通道并等待足够历史', position === null ? '' : `<div class="technical-position" aria-hidden="true"><i style="left:${clampPercent(position)}%"></i></div>`) +
      tile(`真实波幅 · ATR${activeParams.atr_period}`, atr === null ? '—' : `${fmtNum(atr, 2)}<em>%</em>`, squeeze === 1 ? 'BB / KC 波动收缩中' : squeeze === 0 ? previousSqueeze === 1 ? 'BB / KC 刚解除收缩' : 'BB / KC 未收缩' : '历史不足') +
      tile(`量价压力 · CMF${activeParams.cmf_period}`, flow === null ? '—' : `${flow > 0 ? '+' : ''}${fmtNum(flow, 3)}`, flow === null ? '成交量或历史不足' : flow > 0 ? '收盘位置偏向区间上部' : flow < 0 ? '收盘位置偏向区间下部' : '量价压力均衡');
  }

  function paintChartPayload(payload, range) {
    chartEl.classList.remove('chart-loading');
    chartBusy = false;
    const bars = payload.bars || [];
    chartPayload = bars.length ? payload : null;
    if (chartRange !== range) chartZoom = null;
    chartRange = range;
    chartIntraday = Boolean(payload.intraday) && bars.length > 0;
    paintChartToggles();
    paintTechnicalReadout();
    if (!bars.length) {
      if (chartMeta) chartMeta.textContent = '该区间暂无可用行情。';
      chartLegend.innerHTML = '';
      charts.clear(chartEl);
      chartEl.innerHTML = ui.emptyState('暂无行情数据', '上游行情源暂未返回该区间的 K 线。');
      return false;
    }
    if (!chartEl.querySelector('canvas')) chartEl.innerHTML = '';
    $$('[data-range-buttons] button', root).forEach((button) => {
      button.classList.toggle('active', button.dataset.range === range);
    });
    charts.candles(chartEl, {
      bars,
      indicators: payload.indicators || {},
      indicatorParams: payload.indicator_params || chartPrefs.params,
      intraday: chartIntraday,
      interval: payload.interval,
      range,
      overlays: chartPrefs,
      legendEl: chartLegend,
      zoom: chartZoom,
      onZoom: (zoom) => { chartZoom = zoom; },
    });
    if (chartMeta) {
      const interval = { '1m': '1分钟', '5m': '5分钟', '15m': '15分钟', '1d': '日K', '1w': '周K' }[payload.interval] || (chartIntraday ? '分时' : '日K');
      const basis = payload.price_basis === 'forward_adjusted' ? '前复权' : payload.price_basis === 'raw' ? '原始价格' : '';
      chartMeta.textContent = [`${bars.length} 根K线`, interval, sourceLabel(payload.source), basis].filter(Boolean).join(' · ');
    }
    return true;
  }

  async function loadChart(range) {
    const token = ++chartToken;
    chartBusy = true;
    paintChartToggles();
    $$('[data-range-buttons] button', root).forEach((button) => {
      button.classList.toggle('active', button.dataset.range === range);
    });
    chartEl.classList.add('chart-loading');
    if (chartMeta) {
      chartMeta.innerHTML = `<span class="spinner" style="width:12px;height:12px;border-width:1.5px"></span><span>正在加载 ${esc(range)} 行情…</span>`;
    }
    try {
      const customParams = chartParamsQuery();
      const payload = await api.get(`/api/stocks/${encodeURIComponent(symbol)}/chart?range=${encodeURIComponent(range)}${customParams ? `&params=${customParams}` : ''}`, {
        signal,
        timeout: 90000,
      });
      if (token !== chartToken || !isActive() || disposed) return;
      paintChartPayload(payload, range);
    } catch (error) {
      if (error?.name === 'AbortError' || disposed || token !== chartToken || !isActive()) return;
      chartEl.classList.remove('chart-loading');
      chartBusy = false;
      chartPayload = null;
      chartIntraday = false;
      paintChartToggles();
      paintTechnicalReadout();
      chartLegend.innerHTML = '';
      if (chartMeta) chartMeta.innerHTML = `<span class="neg">${esc(error.message || '行情加载失败')}</span>`;
      charts.clear(chartEl);
      chartEl.innerHTML = ui.emptyState('行情加载失败', '请稍后重试或切换其他区间。');
    }
  }

  function paintFinancials() {
    const rows = financialMode === 'annual' ? financials.annual || [] : financials.quarterly || [];
    const view = renderFinancials(rows, financialMode, financials.currency || 'USD', financials.note);
    const chart = $('[data-fin-chart]', root);
    const tiles = $('[data-fin-tiles]', root);
    const note = $('[data-fin-note]', root);
    chart.innerHTML = '';
    if (!rows.length) {
      chart.innerHTML = ui.emptyState('暂无财务数据', '该口径下暂无可用的财务指标。');
    } else {
      charts.financialsChart(chart, rows, financialMode);
    }
    tiles.innerHTML = view.tiles;
    note.textContent = view.note || '数据来自东方财富 F10，单位为美元。';
    $$('[data-fin-mode] button', root).forEach((button) => {
      button.classList.toggle('active', button.dataset.mode === financialMode);
    });
  }

  $$('[data-range-buttons] button', root).forEach((button) => {
    button.addEventListener('click', () => loadChart(button.dataset.range));
  });

  $$('[data-chart-toggle]', root).forEach((button) => {
    const key = button.dataset.chartToggle;
    if (!(key in chartPrefs)) return;
    button.addEventListener('click', () => {
      if (!chartPayload || chartIntraday || chartBusy) return;
      chartPrefs[key] = !chartPrefs[key];
      store.setChartPref(key, chartPrefs[key]);
      paintChartPayload(chartPayload, chartRange);
    });
  });

  const paramSheetEl = $('[data-param-sheet]', root);
  const menuLayer = document.createElement('div');
  menuLayer.className = 'studio-menu-layer';
  $$('.studio-menu', root).forEach((menu) => menuLayer.append(menu));
  document.body.append(menuLayer);

  function closeMenus() {
    $$('.studio-menu', menuLayer).forEach((menu) => {
      menu.hidden = true;
      $$('.keyboard-active', menu).forEach((option) => option.classList.remove('keyboard-active'));
      const trigger = $(`[data-menu-toggle="${menu.dataset.menu}"]`, root);
      trigger?.setAttribute('aria-expanded', 'false');
      trigger?.removeAttribute('aria-activedescendant');
    });
  }

  function positionMenu(trigger, menu) {
    const rect = trigger.getBoundingClientRect();
    const gap = 6;
    const inset = 12;
    menu.style.visibility = 'hidden';
    menu.hidden = false;
    const width = Math.min(330, window.innerWidth - inset * 2);
    menu.style.width = `${width}px`;
    const height = Math.min(menu.scrollHeight, window.innerHeight - inset * 2);
    const left = Math.max(inset, Math.min(rect.left, window.innerWidth - width - inset));
    const below = rect.bottom + gap;
    const top = below + height > window.innerHeight - inset ? Math.max(inset, rect.top - height - gap) : below;
    menu.style.left = `${left}px`;
    menu.style.top = `${top}px`;
    menu.style.visibility = '';
  }

  function toggleParamSheet(force = null) {
    const open = force === null ? paramSheetEl.hidden : Boolean(force);
    paramSheetEl.hidden = !open;
    $('[data-param-toggle]', root).setAttribute('aria-expanded', String(open));
  }

  function refreshGuide() {
    const guide = $('.technical-guide', root);
    if (guide) guide.outerHTML = technicalGuide(chartPrefs.params);
  }

  function commitParams(next, message = true) {
    const changed = JSON.stringify(next) !== JSON.stringify(chartPrefs.params);
    chartPrefs.params = next;
    store.setChartParams(next);
    paramSheetEl.innerHTML = paramSheet(next, chartPrefs);
    paintStudioModules();
    refreshGuide();
    toggleParamSheet(false);
    if (changed) {
      if (message) ui.toast('指标参数已更新', 'success', 1500);
      if (!chartIntraday) loadChart(chartRange);
    }
  }

  const moduleHost = $('.studio-modules', root);
  const highlightMenu = (trigger, menu, value) => {
    $$('.studio-option', menu).forEach((option) => {
      option.classList.toggle('keyboard-active', option.dataset.value === value);
    });
    if (value) trigger.setAttribute('aria-activedescendant', `studio-option-${menu.dataset.menu}-${value}`);
    else trigger.removeAttribute('aria-activedescendant');
  };
  const openMenu = (trigger, initial = null) => {
    const menu = $(`[data-menu="${trigger.dataset.menuToggle}"]`, menuLayer);
    if (!menu) return null;
    closeMenus();
    positionMenu(trigger, menu);
    trigger.setAttribute('aria-expanded', 'true');
    const options = $$('.studio-option', menu);
    const value = initial || menu.querySelector('.selected')?.dataset.value || options[0]?.dataset.value;
    highlightMenu(trigger, menu, initial ? value : null);
    return menu;
  };
  moduleHost.addEventListener('click', (event) => {
    const trigger = event.target.closest('[data-menu-toggle]');
    if (!trigger || trigger.disabled) return;
    const menu = $(`[data-menu="${trigger.dataset.menuToggle}"]`, menuLayer);
    if (!menu) return;
    if (menu.hidden) {
      openMenu(trigger);
    } else {
      closeMenus();
      trigger.setAttribute('aria-expanded', 'false');
    }
  });
  moduleHost.addEventListener('keydown', (event) => {
    const trigger = event.target.closest('[data-menu-toggle]');
    if (!trigger || trigger.disabled) return;
    const menu = $(`[data-menu="${trigger.dataset.menuToggle}"]`, menuLayer);
    if (!menu) return;
    const options = $$('.studio-option', menu);
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      const closed = menu.hidden;
      if (closed) openMenu(trigger);
      const active = menu.querySelector('.keyboard-active')?.dataset.value;
      const index = options.findIndex((option) => option.dataset.value === active);
      const start = index >= 0 ? index : closed ? (event.key === 'ArrowDown' ? -1 : 0) : options.findIndex((option) => option.classList.contains('selected'));
      const step = event.key === 'ArrowDown' ? 1 : -1;
      highlightMenu(trigger, menu, options[(start + step + options.length) % options.length].dataset.value);
    } else if (event.key === 'Enter' || event.key === ' ') {
      if (menu.hidden) return;
      event.preventDefault();
      const active = menu.querySelector('.keyboard-active') || menu.querySelector('.selected');
      closeMenus();
      active?.click();
    } else if (event.key === 'Escape' && !menu.hidden) {
      event.preventDefault();
      closeMenus();
    }
  });
  menuLayer.addEventListener('mousedown', (event) => {
    if (event.target.closest('.studio-option')) event.preventDefault();
  });

  menuLayer.addEventListener('click', (event) => {
    const option = event.target.closest('[data-tech-option]');
    if (!option || !chartPayload || chartIntraday || chartBusy) return;
    const group = option.dataset.techOption;
    const value = option.dataset.value;
    closeMenus();
    const trigger = $(`[data-menu-toggle="${group}"]`, root);
    trigger?.setAttribute('aria-expanded', 'false');
    trigger?.focus({ preventScroll: true });
    if (chartPrefs[group] === value) return;
    chartPrefs[group] = value;
    store.setChartPref(group, value);
    paramSheetEl.innerHTML = paramSheet(chartPrefs.params, chartPrefs);
    paintChartPayload(chartPayload, chartRange);
  });

  menuLayer.addEventListener('keydown', (event) => {
    const menu = $('.studio-menu:not([hidden])', menuLayer);
    if (!menu) return;
    const options = $$('.studio-option', menu);
    const index = options.indexOf(document.activeElement);
    if (event.key === 'Escape') {
      event.preventDefault();
      const group = menu.dataset.menu;
      closeMenus();
      $(`[data-menu-toggle="${group}"]`, root)?.focus({ preventScroll: true });
    } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      const step = event.key === 'ArrowDown' ? 1 : -1;
      options[(index + step + options.length) % options.length]?.focus({ preventScroll: true });
    } else if (event.key === 'Home' || event.key === 'End') {
      event.preventDefault();
      options[event.key === 'Home' ? 0 : options.length - 1]?.focus({ preventScroll: true });
    }
  });

  $('[data-param-toggle]', root).addEventListener('click', () => toggleParamSheet());

  paramSheetEl.addEventListener('click', (event) => {
    if (event.target.closest('[data-param-defaults]')) {
      commitParams(sanitizeIndicatorParams(DEFAULT_INDICATOR_PARAMS));
      return;
    }
    if (!event.target.closest('[data-param-apply]')) return;
    const error = $('[data-param-error]', paramSheetEl);
    const inputs = $$('.studio-param-input', paramSheetEl);
    inputs.forEach((input) => input.removeAttribute('aria-invalid'));
    const invalid = inputs.find((input) => !input.checkValidity());
    if (invalid) {
      invalid.setAttribute('aria-invalid', 'true');
      invalid.focus();
      error.textContent = '请输入范围内的有效参数。';
      error.hidden = false;
      return;
    }
    const next = {};
    inputs.forEach((input) => {
      if (input.dataset.param) next[input.dataset.param] = Number(input.value);
    });
    const periods = $$('[data-ma-index]', paramSheetEl).map((input) => Number(input.value));
    if (new Set(periods).size !== periods.length) {
      error.textContent = '四条均线周期不能重复。';
      error.hidden = false;
      return;
    }
    next.ma_periods = periods;
    const invalidPair = [
      ['MACD', next.macd_fast, next.macd_slow],
      ['KAMA', next.kama_fast, next.kama_slow],
      ['自适应通道', next.adaptive_fast, next.adaptive_slow],
    ].find(([, fast, slow]) => fast >= slow);
    if (invalidPair) {
      error.textContent = `${invalidPair[0]} 快线周期必须小于慢线周期。`;
      error.hidden = false;
      return;
    }
    commitParams(sanitizeIndicatorParams(next));
  });

  const onStudioOutside = (event) => {
    if (!event.target.closest('.studio-module') && !event.target.closest('.studio-menu')) closeMenus();
  };
  const onStudioKeydown = (event) => {
    if (event.key !== 'Escape') return;
    closeMenus();
    if (!paramSheetEl.hidden) toggleParamSheet(false);
  };
  const onStudioScroll = () => closeMenus();
  const onStudioFocusOut = () => {
    requestAnimationFrame(() => {
      if (!moduleHost.contains(document.activeElement) && !menuLayer.contains(document.activeElement)) closeMenus();
    });
  };
  document.addEventListener('click', onStudioOutside);
  document.addEventListener('keydown', onStudioKeydown);
  moduleHost.addEventListener('focusout', onStudioFocusOut);
  window.addEventListener('scroll', onStudioScroll, true);
  window.addEventListener('resize', onStudioScroll);

  $$('[data-tech-preset]', root).forEach((button) => {
    button.addEventListener('click', () => {
      if (!chartPayload || chartIntraday || chartBusy) return;
      Object.entries(TECH_PRESETS[button.dataset.techPreset]).forEach(([key, value]) => {
        if (key === 'name') return;
        chartPrefs[key] = value;
        store.setChartPref(key, value);
      });
      paramSheetEl.innerHTML = paramSheet(chartPrefs.params, chartPrefs);
      paintChartPayload(chartPayload, chartRange);
    });
  });

  $('[data-chart-reset]', root).addEventListener('click', () => {
    if (!chartPayload || chartIntraday || chartBusy) return;
    chartZoom = { start: 0, end: 100 };
    paintChartPayload(chartPayload, chartRange);
  });

  $('[data-chart-export]', root)?.addEventListener('click', () => {
    if (!chartPayload) {
      ui.toast('图表尚未加载完成，暂时无法导出', 'info', 1800);
      return;
    }
    const ok = charts.exportPNG(chartEl, `${symbol}-${chartRange}.png`);
    ui.toast(ok ? '图表已导出为 PNG' : '导出失败，请稍后重试', ok ? 'success' : 'error', 2000);
  });

  function onChartKeydown(event) {
    if (disposed || !isActive() || event.defaultPrevented) return;
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    const target = event.target;
    if (
      target &&
      (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT' || target.isContentEditable)
    ) {
      return;
    }
    const index = '1234567890'.indexOf(event.key);
    if (index < 0) return;
    const next = RANGES[index];
    if (!next) return;
    event.preventDefault();
    if (next !== chartRange) loadChart(next);
  }
  document.addEventListener('keydown', onChartKeydown);

  $$('[data-fin-mode] button', root).forEach((button) => {
    button.addEventListener('click', () => {
      if (financialMode === button.dataset.mode) return;
      financialMode = button.dataset.mode;
      paintFinancials();
    });
  });

  $('[data-star]', root)?.addEventListener('click', () => {
    const on = store.toggleWatch(symbol);
    paintStar();
    ui.toast(on ? `已添加 ${symbol} 到自选` : `已从自选移除 ${symbol}`, on ? 'success' : 'info', 2000);
  });

  const onWatchStore = (event) => {
    if (event.detail?.type === 'watchlist') paintStar();
  };
  window.addEventListener('starmap:store', onWatchStore);

  $('[data-expand-profile]', root)?.addEventListener('click', (event) => {
    const desc = $('[data-profile-desc]', root);
    if (!desc) return;
    const expanded = desc.classList.toggle('expanded');
    event.currentTarget.textContent = expanded ? '收起' : '展开全文';
  });

  root.addEventListener('click', (event) => {
    if (event.target.closest('button, a, input, select')) return;
    const target = event.target.closest('[data-symbol]');
    if (target?.dataset.symbol) navigate(target.dataset.symbol);
  });

  function paintCashflow(rows) {
    const cashflowEl = $('[data-cashflow]', root);
    const cashflowMeta = $('[data-cashflow-meta]', root);
    const items = (rows || [])
      .filter((row) => row.ocf !== null && row.ocf !== undefined)
      .map((row) => ({ date: row.date, ocf: row.ocf, capex: row.capex, fcf: row.fcf }));
    if (!items.length) {
      if (cashflowMeta) cashflowMeta.textContent = 'SEC 暂未返回可用现金流数据（银行、ETF 等可能不适用）。';
      cashflowEl.innerHTML = ui.emptyState('暂无现金流数据', 'SEC XBRL 中未找到经营现金流与资本开支标签。');
      return;
    }
    if (cashflowMeta) cashflowMeta.textContent = `${items.length} 个财年 · SEC EDGAR XBRL · 单位：美元`;
    charts.cashflowChart(cashflowEl, items);
  }

  function paintSec() {
    if (!secPayload) return;
    const bucket = secPayload[secMode] || {};
    const rows = bucket.rows || [];
    const ratios = bucket.ratios || [];
    const chart = $('[data-sec-chart]', root);
    const tiles = $('[data-sec-tiles]', root);
    const facts = $('[data-sec-facts]', root);
    const insights = $('[data-sec-insights]', root);
    const meta = $('[data-sec-meta]', root);
    $$('[data-sec-mode] button', root).forEach((button) => {
      button.classList.toggle('active', button.dataset.smode === secMode);
      button.disabled = !((secPayload[button.dataset.smode] || {}).rows || []).length;
    });
    chart.innerHTML = '';
    if (!secPayload.available || !rows.length) {
      chart.innerHTML = ui.emptyState('暂无 SEC 财务数据', secPayload.message || '该标的可能为 ETF 或未在美国注册。');
      tiles.innerHTML = '';
      if (facts) facts.innerHTML = '';
      insights.innerHTML = '';
      if (meta) meta.textContent = '';
      return;
    }
    charts.earningsQualityChart(chart, rows, ratios, secMode);
    tiles.innerHTML = renderSecTiles(ratios, rows);
    if (facts) facts.innerHTML = renderSecFacts(secPayload, secMode);
    insights.innerHTML = renderSecInsights(secPayload.insights);
    if (meta) {
      meta.innerHTML = `${rows.length} 个${secMode === 'annual' ? '财年' : '单季'} · ${esc(secPayload.company || symbol)} · SEC EDGAR XBRL${secPayload.is_financial ? ' · 金融企业口径' : ''}`;
    }
  }

  async function loadStatements() {
    const meta = $('[data-sec-meta]', root);
    try {
      const payload = await api.get(`/api/stocks/${encodeURIComponent(symbol)}/statements`, {
        signal,
        timeout: 120000,
      });
      if (!isActive() || disposed) return;
      secPayload = payload;
      secMode = (payload.annual?.rows || []).length ? 'annual' : 'quarterly';
      paintSec();
      paintCashflow(payload.annual?.rows || []);
    } catch (error) {
      if (error?.name === 'AbortError' || disposed) return;
      if (meta) meta.innerHTML = `<span class="neg">${esc(error.message || 'SEC 财报读取失败')}</span>`;
      const chart = $('[data-sec-chart]', root);
      if (chart) chart.innerHTML = ui.emptyState('SEC 财报数据不可用', 'EDGAR companyfacts 暂时无法访问，请稍后刷新。');
      const cashflowMeta = $('[data-cashflow-meta]', root);
      if (cashflowMeta) cashflowMeta.innerHTML = `<span class="neg">${esc(error.message || 'SEC 现金流读取失败')}</span>`;
      const cashflowEl = $('[data-cashflow]', root);
      if (cashflowEl) cashflowEl.innerHTML = ui.emptyState('现金流数据不可用', 'SEC EDGAR 暂时无法访问，请稍后刷新。');
    }
  }

  function paintMda() {
    const body = $('[data-mda-body]', root);
    if (!body || !mdaPayload) return;
    $$('[data-mda-mode] button', root).forEach((button) => {
      const bucket = mdaPayload[button.dataset.mmode];
      button.classList.toggle('active', button.dataset.mmode === mdaMode);
      button.disabled = !bucket?.mda;
    });
    if (!mdaPayload.available) {
      body.innerHTML = ui.emptyState('MD&A 文本分析不适用', mdaPayload.message || 'EDGAR 未收录该标的。');
      return;
    }
    const notes = [
      ...(mdaPayload.notes || []),
      ...(mdaPayload.warnings || []).map((text) => ({ text, tone: 'caution', scope: 'all' })),
    ];
    body.innerHTML = renderMdaReport(mdaPayload[mdaMode], notes, mdaMode);
  }

  async function loadMda() {
    const body = $('[data-mda-body]', root);
    try {
      const payload = await api.get(`/api/stocks/${encodeURIComponent(symbol)}/mda`, {
        signal,
        timeout: 180000,
      });
      if (!isActive() || disposed) return;
      mdaPayload = payload;
      mdaMode = payload.annual?.mda ? 'annual' : 'quarterly';
      paintMda();
    } catch (error) {
      if (error?.name === 'AbortError' || disposed) return;
      if (body) body.innerHTML = ui.emptyState('MD&A 解析失败', error.message || 'EDGAR 原文暂时无法访问，请稍后刷新。');
    }
  }

  $$('[data-sec-mode] button', root).forEach((button) => {
    button.addEventListener('click', () => {
      if (secMode === button.dataset.smode) return;
      secMode = button.dataset.smode;
      paintSec();
    });
  });

  $$('[data-mda-mode] button', root).forEach((button) => {
    button.addEventListener('click', () => {
      if (mdaMode === button.dataset.mmode) return;
      mdaMode = button.dataset.mmode;
      paintMda();
    });
  });

  if (!financialView.chart) {
    const finChart = $('[data-fin-chart]', root);
    charts.financialsChart(finChart, initialFinancialRows, initialFinancialMode);
  }

  const initialChart = data.chart || {};
  if (!paintChartPayload(initialChart, initialChart.range || '1Y')) {
    loadChart('1Y');
  }
  loadStatements();
  loadMda();

  return () => {
    disposed = true;
    chartToken += 1;
    document.removeEventListener('keydown', onChartKeydown);
    document.removeEventListener('click', onStudioOutside);
    document.removeEventListener('keydown', onStudioKeydown);
    moduleHost.removeEventListener('focusout', onStudioFocusOut);
    window.removeEventListener('scroll', onStudioScroll, true);
    window.removeEventListener('resize', onStudioScroll);
    window.removeEventListener('starmap:store', onWatchStore);
    menuLayer.remove();
  };
}
