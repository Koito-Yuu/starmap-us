import { api } from '../api.js';
import * as ui from '../ui.js';
import * as charts from '../charts.js';
import { $, esc, fmtDate, fmtNum, tone } from '../utils.js';
import { asOfBadge, viewHead } from './common.js';

export const meta = {
  title: '宏观雷达',
  eyebrow: 'MACRO RADAR',
};

const SERIES_META = [
  { id: 'DGS3MO', label: '3 个月美债收益率', unit: '%', group: '利率与利差' },
  { id: 'DGS2', label: '2 年期美债收益率', unit: '%', group: '利率与利差' },
  { id: 'DGS5', label: '5 年期美债收益率', unit: '%', group: '利率与利差' },
  { id: 'DGS10', label: '10 年期美债收益率', unit: '%', group: '利率与利差' },
  { id: 'DGS30', label: '30 年期美债收益率', unit: '%', group: '利率与利差' },
  { id: 'T10Y2Y', label: '10Y-2Y 利差', unit: '%', group: '利率与利差' },
  { id: 'T10Y3M', label: '10Y-3M 利差', unit: '%', group: '利率与利差' },
  { id: 'DFII10', label: '10 年期实际收益率', unit: '%', group: '利率与利差' },
  { id: 'T10YIE', label: '10 年期盈亏平衡通胀', unit: '%', group: '利率与利差' },
  { id: 'T5YIFR', label: '5y5y 远期通胀预期', unit: '%', group: '利率与利差' },
  { id: 'FEDFUNDS', label: '联邦基金利率', unit: '%', group: '利率与利差' },
  { id: 'DFEDTARU', label: '联邦基金目标区间上限', unit: '%', group: '美联储政策' },
  { id: 'DFEDTARL', label: '联邦基金目标区间下限', unit: '%', group: '美联储政策' },
  { id: 'EFFR', label: '有效联邦基金利率 EFFR', unit: '%', group: '美联储政策' },
  { id: 'SOFR', label: '担保隔夜融资利率 SOFR', unit: '%', group: '美联储政策' },
  { id: 'IORB', label: '准备金余额利率 IORB', unit: '%', group: '美联储政策' },
  { id: 'RRPONTSYD', label: '隔夜逆回购规模', unit: '十亿美元', group: '美联储政策' },
  { id: 'WRESBAL', label: '银行准备金余额', unit: '十亿美元', group: '美联储政策' },
  { id: 'CPIAUCSL', label: 'CPI 同比', unit: '%', group: '通胀' },
  { id: 'CPILFESL', label: '核心 CPI 同比', unit: '%', group: '通胀' },
  { id: 'PCEPILFE', label: '核心 PCE 同比', unit: '%', group: '通胀' },
  { id: 'UNRATE', label: '美国失业率', unit: '%', group: '就业' },
  { id: 'ICSA', label: '初请失业金人数', unit: '人', group: '就业' },
  { id: 'PAYEMS', label: '非农就业人数', unit: '千人', group: '就业' },
  { id: 'CFNAI', label: '芝加哥联储全国活动指数', unit: '', group: '增长与房地产' },
  { id: 'PERMIT', label: '新屋许可', unit: '千套', group: '增长与房地产' },
  { id: 'GDPC1', label: '美国实际 GDP 同比', unit: '%', group: '增长与房地产' },
  { id: 'UMCSENT', label: '密歇根消费者信心', unit: '', group: '增长与房地产' },
  { id: 'BAMLH0A0HYM2', label: '美国高收益债 OAS', unit: '%', group: '信用与流动性' },
  { id: 'BAA10Y', label: 'Baa-10Y 信用利差', unit: '%', group: '信用与流动性' },
  { id: 'NFCI', label: '芝加哥联储金融条件', unit: '', group: '信用与流动性' },
  { id: 'M2SL', label: 'M2 货币供应', unit: '十亿美元', group: '信用与流动性' },
  { id: 'WALCL', label: '美联储总资产', unit: '百万美元', group: '信用与流动性' },
  { id: 'VIXCLS', label: 'VIX 恐慌指数', unit: '', group: '市场' },
  { id: 'DTWEXBGS', label: '美元指数（广义）', unit: '', group: '市场' },
];
const SERIES_MAP = Object.fromEntries(SERIES_META.map((item) => [item.id, item]));
const YEARS = [1, 3, 5, 10, 20, 40];
const THRESHOLDS = { T10Y2Y: 0, T10Y3M: 0, VIXCLS: 30, NFCI: 0, CFNAI: 0 };
const COLORS = {
  T10Y2Y: '#8b93ff', T10Y3M: '#5ad1ff', CPIAUCSL: '#f0b35a', CPILFESL: '#f65c6c',
  PCEPILFE: '#c084fc', VIXCLS: '#f0b35a', DTWEXBGS: '#4fd1c5', GDPC1: '#8b93ff',
  UNRATE: '#5ad1ff', ICSA: '#f0b35a', PAYEMS: '#34d399', CFNAI: '#4fd1c5',
  PERMIT: '#8b93ff', BAMLH0A0HYM2: '#f65c6c', BAA10Y: '#f0b35a', NFCI: '#4fd1c5', M2SL: '#8b93ff',
  WALCL: '#f0b35a', DFII10: '#f0b35a', T10YIE: '#4fd1c5', T5YIFR: '#8b93ff',
  DFEDTARU: '#5ad1ff', DFEDTARL: '#8b93ff', EFFR: '#f0b35a', SOFR: '#4fd1c5', IORB: '#c084fc',
  RRPONTSYD: '#8b93ff', WRESBAL: '#f0b35a',
};

function seriesOptions(selected) {
  const groups = Array.from(new Set(SERIES_META.map((item) => item.group)));
  return groups.map((group) => `<optgroup label="${esc(group)}">${SERIES_META.filter((item) => item.group === group)
    .map((item) => `<option value="${item.id}" ${item.id === selected ? 'selected' : ''}>${esc(item.label)}</option>`)
    .join('')}</optgroup>`).join('');
}

function macroCard(card) {
  const digits = card.decimals ?? 2;
  const deltaTone = card.delta === null || card.delta === undefined ? 'flat' : tone(card.delta);
  const deltaText = card.delta === null || card.delta === undefined ? '—' : `${card.delta > 0 ? '+' : ''}${fmtNum(card.delta, digits)}`;
  const cardTargets = { HY_OAS: 'BAMLH0A0HYM2', CFNAI_3M: 'CFNAI' };
  const target = cardTargets[card.id] || (SERIES_MAP[card.id] ? card.id : '');
  return `<button type="button" class="macro-card" ${target ? `data-series="${esc(target)}"` : 'disabled'} title="查看 ${esc(card.label)} 历史序列">
    <div class="mc-label">${esc(card.label)}</div>
    <div class="mc-value">${fmtNum(card.value, digits)}<small>${esc(card.unit === 'index' ? '' : card.unit || '')}</small></div>
    <div class="mc-foot"><span class="mc-delta">${esc(card.delta_label || '较上期')} <b class="${deltaTone}">${deltaText}</b></span><span>${esc(fmtDate(card.as_of, 'month'))}</span></div>
  </button>`;
}

function panel({ title, sub = '', body, tag = 'FRED' }) {
  return `<section class="panel"><div class="panel-head"><div class="panel-title">${esc(title)} ${sub ? `<span class="sub">${esc(sub)}</span>` : ''} <span class="tag">${esc(tag)}</span></div></div><div class="chart-body">${body}</div></section>`;
}

function hasPoints(points) { return Array.isArray(points) && points.length > 1; }
function sectionHead(title, sub) { return `<div class="macro-section-head"><div><span>${esc(title)}</span><small>${esc(sub)}</small></div></div>`; }

function weatherCard({ label, value, sub, detail, level = 'neutral' }) {
  return `<div class="macro-weather-card ${esc(level)}"><span>${esc(label)}</span><strong>${value}</strong><small>${esc(sub)}</small><p>${esc(detail || '')}</p></div>`;
}

const WATCH_LABELS = { triggered: '触发', watch: '观察', clear: '未触发', unknown: '数据不足' };
const WATCH_TONES = { triggered: 'danger', watch: 'warning', clear: 'ok', unknown: 'neutral' };

function recessionWatch(rows) {
  if (!rows?.length) return ui.emptyState('监控项暂不可用', 'FRED 未返回足够的宏观数据。');
  return `<div class="macro-watch-list">${rows.map((item) => {
    const status = WATCH_LABELS[item.status] || WATCH_LABELS.unknown;
    const level = WATCH_TONES[item.status] || 'neutral';
    const raw = item.value === null || item.value === undefined ? '—' : item.value;
    return `<div class="macro-watch-row ${level}" title="${esc(item.threshold_note || '')}">
      <span class="macro-watch-mark"></span>
      <div class="macro-watch-copy"><b>${esc(item.label)}</b><small>${esc(item.detail || item.threshold_note || '')}</small></div>
      <strong>${esc(String(raw))}${esc(item.unit || '')}</strong><em>${esc(status)}</em>
    </div>`;
  }).join('')}</div>`;
}

function metricPill(label, value, unit = '', toneClass = '') {
  return `<span class="macro-metric-pill"><span>${esc(label)}</span><b class="${esc(toneClass)}">${value}${esc(unit)}</b></span>`;
}

function fomcTile(label, value, sub) {
  return `<div class="fomc-tile"><span>${esc(label)}</span><strong>${value}</strong><small>${esc(sub)}</small></div>`;
}

function signedPp(value, digits = 2) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—';
  const number = Number(value);
  return `${number > 0 ? '+' : ''}${fmtNum(number, digits)}pp`;
}

function fomcSection(data) {
  const fomc = data.fomc || {};
  const policy = fomc.policy || data.policy || {};
  const balance = policy.balance_sheet || {};
  const next = fomc.next_meeting;
  const statement = fomc.latest_statement;
  const upcoming = (fomc.upcoming || []).slice(0, 4);
  const recent = (fomc.recent || []).filter((item) => item.statement_url).slice(0, 6);
  const corridor = data.series?.policy_corridor || {};
  const target = policy.target_lower !== null && policy.target_lower !== undefined && policy.target_upper !== null && policy.target_upper !== undefined
    ? `${fmtNum(policy.target_lower, 2)}%–${fmtNum(policy.target_upper, 2)}%`
    : '—';
  const mid = policy.target_mid !== null && policy.target_mid !== undefined ? `${fmtNum(policy.target_mid, 3)}%` : '—';
  const realPolicy = policy.real_policy_pce !== null && policy.real_policy_pce !== undefined ? `${fmtNum(policy.real_policy_pce, 2)}%` : '—';
  const meetingLabel = next?.date
    ? `${Number(next.date.slice(5, 7))} 月 ${esc(next.day_range || next.date.slice(8))} 日`
    : '—';
  const meetingDays = next?.days_until === null || next?.days_until === undefined ? '' : `${next.days_until} 天后`;
  const sepUrl = statement?.sep_url || fomc.latest_sep?.url;
  const sepDate = statement?.sep_url ? statement.date : fomc.latest_sep?.date;
  const links = statement ? [
    statement.url ? `<a href="${esc(statement.url)}" target="_blank" rel="noopener noreferrer">声明原文 ${ui.icon('external', 11)}</a>` : '',
    statement.implementation_note_url ? `<a href="${esc(statement.implementation_note_url)}" target="_blank" rel="noopener noreferrer">实施说明</a>` : '',
    statement.minutes_url ? `<a href="${esc(statement.minutes_url)}" target="_blank" rel="noopener noreferrer">会议纪要</a>` : '',
    sepUrl ? `<a href="${esc(sepUrl)}" target="_blank" rel="noopener noreferrer">SEP / 点阵图${sepDate ? ` (${esc(sepDate)})` : ''}</a>` : '',
  ].filter(Boolean).join('') : '';
  const upcomingRows = upcoming.length
    ? upcoming.map((item) => `<div class="fomc-upcoming-row">
        <span>${esc(item.date)}</span>
        <b>${Number(item.date.slice(5, 7))} 月 ${esc(item.day_range || item.date.slice(8))} 日</b>
        <em>${item.days_until === null || item.days_until === undefined ? '—' : `${item.days_until} 天`}</em>
        ${item.has_projections ? '<i>SEP</i>' : ''}
      </div>`).join('')
    : '<p class="fomc-empty">官方日历暂未返回未来会议。</p>';
  return `${sectionHead('美联储与 FOMC', '政策走廊、官方会议与最近声明')}
    <div class="fomc-grid">
      <section class="panel fomc-policy-card">
        <div class="panel-head">
          <div class="panel-title">政策走廊 <span class="sub">目标区间与短端利率</span></div>
          <div class="panel-actions"><span class="badge">FRED · 官方</span></div>
        </div>
        <div class="panel-body">
          <div class="fomc-tiles">
            ${fomcTile('目标区间', target, `中值 ${mid}`)}
            ${fomcTile('有效利率 EFFR', policy.effective !== null && policy.effective !== undefined ? `${fmtNum(policy.effective, 2)}%` : '—', `SOFR ${policy.sofr !== null && policy.sofr !== undefined ? `${fmtNum(policy.sofr, 2)}%` : '—'} · IORB ${policy.iorb !== null && policy.iorb !== undefined ? `${fmtNum(policy.iorb, 2)}%` : '—'}`)}
            ${fomcTile('实际政策利率', realPolicy, `目标中值 − 核心 PCE ${policy.core_pce_yoy !== null && policy.core_pce_yoy !== undefined ? `${fmtNum(policy.core_pce_yoy, 2)}%` : '—'}`)}
            ${fomcTile('目标区间变化', signedPp(policy.target_change_12m), `6 个月 ${signedPp(policy.target_change_6m)}`)}
          </div>
          <div class="chart" data-fomc-corridor style="height:226px"></div>
          <div class="fomc-balance-strip">
            <div><span>联储总资产</span><b>${balance.total_assets_trillion !== null && balance.total_assets_trillion !== undefined ? `$${fmtNum(balance.total_assets_trillion, 2)}T` : '—'}</b><small>${balance.total_assets_change_13w_bn !== null && balance.total_assets_change_13w_bn !== undefined ? `13 周 ${signedPp(balance.total_assets_change_13w_bn, 1).replace('pp', 'B')}` : '13 周变化暂无'}</small></div>
            <div><span>银行准备金</span><b>${balance.reserves_trillion !== null && balance.reserves_trillion !== undefined ? `$${fmtNum(balance.reserves_trillion, 2)}T` : '—'}</b><small>${balance.reserves_change_13w_bn !== null && balance.reserves_change_13w_bn !== undefined ? `13 周 ${signedPp(balance.reserves_change_13w_bn, 1).replace('pp', 'B')}` : '13 周变化暂无'}</small></div>
            <div><span>隔夜逆回购</span><b>${balance.on_rrp_bn !== null && balance.on_rrp_bn !== undefined ? `$${fmtNum(balance.on_rrp_bn, 0)}B` : '—'}</b><small>${esc(balance.as_of || '—')}</small></div>
          </div>
          <p class="fomc-note">${esc(policy.note || '目标区间与短端利率来自 FRED 官方发布值。')} ${hasPoints(corridor.target_upper) ? '折线展示目标上下限、EFFR 与 SOFR。' : ''}</p>
          <div class="fomc-recent-head"><span>最近会议</span><small>官方声明</small></div>
          <div class="fomc-recent">${recent.length
            ? recent.map((item) => `<a href="${esc(item.statement_url)}" target="_blank" rel="noopener noreferrer"><span>${esc(item.date)}</span><b>${Number(item.date.slice(5, 7))} 月 ${esc(item.day_range || item.date.slice(8))} 日</b><i>${item.has_projections ? 'SEP' : ''}</i>${ui.icon('external', 11)}</a>`).join('')
            : '<p class="fomc-empty">暂无已发布声明。</p>'}</div>
        </div>
      </section>
      <section class="panel fomc-meeting-card">
        <div class="panel-head">
          <div class="panel-title">FOMC 日历 <span class="sub">Federal Reserve Board</span></div>
          <div class="panel-actions"><a class="btn small ghost" href="${esc(fomc.source_url || 'https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm')}" target="_blank" rel="noopener noreferrer">官方日历 ${ui.icon('external', 11)}</a></div>
        </div>
        <div class="panel-body">
          <div class="fomc-next">
            <div><span>下一次会议</span><strong>${meetingLabel}</strong><small>${esc(next?.date || '—')}</small></div>
            <em>${esc(meetingDays)}</em>
          </div>
          <div class="fomc-upcoming-head"><span>未来会议</span><small>SEP 标记为季度预测会议</small></div>
          <div class="fomc-upcoming">${upcomingRows}</div>
          <div class="fomc-statement">
            <div class="fomc-statement-head"><span>最近声明</span><small>${esc(statement?.date || '—')} · 英文原文</small></div>
            ${statement
              ? `<p class="fomc-decision">${esc(statement.excerpt || statement.decision || '官方声明已发布。')}</p>
                 ${statement.vote || statement.dissent ? `<div class="fomc-vote">${statement.vote ? `投票 ${esc(statement.vote)}` : ''}${statement.dissent ? `<span>${esc(statement.dissent)}</span>` : ''}</div>` : ''}
                 <div class="fomc-links">${links}</div>`
              : `<p class="fomc-empty">最近声明暂不可用，可通过官方日历查看。</p>`}
          </div>
          ${fomc.latest_minutes?.url ? `<p class="fomc-minutes">最近纪要：<a href="${esc(fomc.latest_minutes.url)}" target="_blank" rel="noopener noreferrer">${esc(fomc.latest_minutes.date)}${fomc.latest_minutes.released ? ` · 发布于 ${esc(fomc.latest_minutes.released)}` : ''}</a></p>` : ''}
          <div class="fomc-cadence"><span>发布节奏</span><p>声明在会议结束日 14:00 ET 发布；会议纪要通常约三周后发布；SEP 预测在每年 3、6、9、12 月会议后发布。</p></div>
          <p class="fomc-note">${esc(fomc.note || '会议日期、声明与纪要来自 Federal Reserve Board；点阵图仅链接官方 SEP，不在本项目内推算。')}</p>
        </div>
      </section>
    </div>`;
}

export async function mount(root, params, ctx) {
  const { signal, isActive } = ctx;
  const initialSeries = String(params.series || '').toUpperCase();
  const state = { seriesId: SERIES_MAP[initialSeries] ? initialSeries : 'DGS10', years: 10, seriesToken: 0, disposed: false };

  root.innerHTML = `<section class="view">${viewHead({
    eyebrow: meta.eyebrow, title: '宏观雷达', sub: '利率、通胀、就业、信用与流动性环境的统一观察框架。',
    actions: '<span class="as-of"><span class="dot"></span>正在同步 FRED…</span>',
  })}<div class="panel">${ui.loadingInline('正在加载 FRED 宏观序列…')}</div></section>`;

  let data;
  let initialExplorer = null;
  try {
    const [overview, explorer] = await Promise.all([
      api.get('/api/macro/overview', { signal, timeout: 150000 }),
      api.get(`/api/macro/series/${encodeURIComponent(state.seriesId)}?years=${state.years}`, { signal, timeout: 60000 }).catch(() => null),
    ]);
    data = overview;
    initialExplorer = explorer;
  } catch (error) {
    if (error?.name === 'AbortError') return undefined;
    root.innerHTML = `<section class="view">${viewHead({ eyebrow: meta.eyebrow, title: '宏观雷达', sub: '未能加载 FRED 宏观数据。' })}<div class="panel">${ui.errorPanel(error.message || '宏观数据加载失败')}</div></section>`;
    ui.bindRetry(root, () => ctx.reload());
    return undefined;
  }
  if (!isActive()) return undefined;

  const series = data.series || {};
  const cards = data.cards || [];
  const curve = data.curve || {};
  const rates = data.real_rates || {};
  const inflation = data.inflation || {};
  const labor = data.labor || {};
  const growth = data.growth || {};
  const credit = data.credit || {};
  const cycle = data.cycle || {};
  const cycleTrail = cycle.trail || [];
  const cycleCurrent = cycle.current || (cycle.x !== null && cycle.x !== undefined
    ? { x: cycle.x, y: cycle.y, date: cycle.latest_date || cycle.as_of }
    : null);
  const curveCurrent = curve.current || data.yield_curve || [];
  const curveYearAgo = curve.one_year_ago || curve['1y'] || curve.year_ago || data.yield_curve_1y || [];
  const yieldRegime = curve.regime || data.curve_regime || {};
  const phaseTone = cycle.phase === 'stagflation' ? 'warning' : cycle.phase === 'slowdown' ? 'neutral' : cycle.phase === 'recovery' ? 'ok' : 'watch';
  const claims = (series.labor?.claims_4wk || []).map((point) => ({ d: point.d, v: Number(point.v) / 1000 }));
  const payroll = series.labor?.payroll_change || [];
  const chips = [
    inflation.core_pce_yoy !== null && inflation.core_pce_yoy !== undefined ? metricPill('核心 PCE', fmtNum(inflation.core_pce_yoy, 2), '%') : '',
    inflation.cpi_3m_annualized !== null && inflation.cpi_3m_annualized !== undefined ? metricPill('CPI 3m 年化', fmtNum(inflation.cpi_3m_annualized, 2), '%') : '',
    rates.real_policy !== null && rates.real_policy !== undefined ? metricPill('实际政策利率', fmtNum(rates.real_policy, 2), '%', tone(rates.real_policy)) : '',
  ].filter(Boolean).join('');

  const weather = [
    weatherCard({ label: '周期象限', value: esc(cycle.label || '数据不足'), sub: '增长动能 × 核心通胀', detail: cycle.detail || '按 CFNAI 三个月均值与核心 CPI 同比定位，环境分类而非预测。', level: phaseTone }),
    weatherCard({ label: '期限结构', value: esc(yieldRegime.label || '—'), sub: curve.spreads?.[0]?.name ? `${curve.spreads[0].name} ${fmtNum(curve.spreads[0].current, 2)}%` : '10Y-2Y 曲线形态', detail: yieldRegime.detail || '按 10Y 与 2Y 过去 21 个交易日变化判断。', level: Number(curve.spreads?.[0]?.current) < 0 ? 'danger' : 'neutral' }),
    weatherCard({ label: '信用利差', value: credit.hy_oas !== null && credit.hy_oas !== undefined ? `${fmtNum(credit.hy_oas, 2)}<small>%</small>` : '—', sub: credit.hy_change_3m !== null && credit.hy_change_3m !== undefined ? `3 个月 ${credit.hy_change_3m > 0 ? '+' : ''}${fmtNum(credit.hy_change_3m, 2)}pct` : '高收益债 OAS', detail: credit.hy_oas >= 5 ? '利差处于压力区间，关注再融资与违约周期。' : '利差反映高收益债相对国债的风险补偿。', level: credit.hy_oas >= 6 ? 'danger' : credit.hy_oas >= 4.5 ? 'warning' : 'ok' }),
    weatherCard({ label: '金融条件', value: credit.nfci !== null && credit.nfci !== undefined ? fmtNum(credit.nfci, 2) : '—', sub: 'NFCI · 负值偏宽松', detail: credit.nfci > 0.5 ? '金融条件偏紧，信用扩张与风险资产承压。' : '金融条件整体处于宽松或中性区间。', level: credit.nfci > 0.5 ? 'warning' : 'ok' }),
  ].join('');

  const panels = {
    'yield-curve': { title: '收益率曲线', sub: '当前 vs 一年前 · 3M–30Y', render: (el) => charts.yieldCurve(el, curveCurrent, curveYearAgo), empty: !hasPoints(curveCurrent) },
    yields: { title: '美债收益率历史', sub: '3M / 2Y / 10Y / 30Y · 近 5 年', render: (el) => charts.macroMultiLine(el, [
      { name: '3M', points: series.yields?.DGS3MO }, { name: '2Y', points: series.yields?.DGS2 },
      { name: '10Y', points: series.yields?.DGS10 }, { name: '30Y', points: series.yields?.DGS30 },
    ], { unit: '%' }), empty: !hasPoints(series.yields?.DGS10) },
    'real-rates': { title: '实际利率与通胀补偿', sub: '10Y 实际收益率 / 盈亏平衡 / 5y5y', render: (el) => charts.macroMultiLine(el, [
      { name: '10Y 实际收益率', points: series.rates?.real10 }, { name: '10Y 盈亏平衡', points: series.rates?.breakeven },
      { name: '5y5y 远期通胀', points: series.rates?.forward5y5y, dashed: true },
    ], { unit: '%' }), empty: !hasPoints(series.rates?.real10) },
    inflation: { title: '通胀趋势', sub: 'CPI / 核心 CPI / 核心 PCE 同比', render: (el) => charts.macroMultiLine(el, [
      { name: 'CPI 同比', points: series.inflation?.cpi }, { name: '核心 CPI 同比', points: series.inflation?.core },
      { name: '核心 PCE 同比', points: series.inflation?.core_pce },
    ], { unit: '%' }), empty: !hasPoints(series.inflation?.cpi) },
    labor: { title: '失业与 Sahm 规则', sub: `失业率 ${fmtNum(labor.unrate, 1)}% · Sahm ${fmtNum(labor.sahm, 2)}pct`, render: (el) => charts.macroMultiLine(el, [
      { name: '失业率', points: series.labor?.unrate }, { name: 'Sahm 规则', points: series.labor?.sahm },
    ], { unit: '%' }), empty: !hasPoints(series.labor?.unrate) },
    'labor-flows': { title: '就业流量', sub: '初请 4 周均值 vs 非农月度增量 · 千人', render: (el) => charts.macroMultiLine(el, [
      { name: '初请 4 周均值', points: claims }, { name: '非农月度增量', points: payroll },
    ], { unit: 'k' }), empty: !hasPoints(claims) && !hasPoints(payroll) },
    growth: { title: '增长与住房', sub: '实际 GDP 同比 · 新屋许可同比', render: (el) => charts.macroMultiLine(el, [
      { name: '实际 GDP 同比', points: series.growth?.gdp_yoy }, { name: '新屋许可同比', points: series.growth?.permits },
    ], { unit: '%' }), empty: !hasPoints(series.growth?.gdp_yoy) && !hasPoints(series.growth?.permits) },
    credit: { title: '信用利差结构', sub: `高收益 OAS ${fmtNum(credit.hy_oas, 2)}% · Baa-10Y ${fmtNum(credit.baa10y, 2)}%`, render: (el) => charts.macroMultiLine(el, [
      { name: '高收益债 OAS（约3年）', points: series.credit?.hy_oas },
      { name: 'Baa-10Y（长历史）', points: series.credit?.baa10y, dashed: true },
    ], { unit: '%' }), empty: !hasPoints(series.credit?.hy_oas) && !hasPoints(series.credit?.baa10y) },
    nfci: { title: '金融条件指数', sub: `NFCI ${fmtNum(credit.nfci, 2)} · 0 为长期均值`, render: (el) => charts.macroLine(el, series.credit?.nfci, { name: 'NFCI', unit: '', threshold: 0, hex: COLORS.NFCI }), empty: !hasPoints(series.credit?.nfci) },
    liquidity: { title: '货币与准备金环境', sub: 'M2 同比 · 美联储总资产同比', render: (el) => charts.macroMultiLine(el, [
      { name: 'M2 同比', points: series.liquidity?.m2_yoy }, { name: '联储总资产同比', points: series.liquidity?.walcl_yoy },
    ], { unit: '%' }), empty: !hasPoints(series.liquidity?.m2_yoy) && !hasPoints(series.liquidity?.walcl_yoy) },
    vix: { title: '市场波动', sub: 'VIX · 近 3 年 · 阈值 30', render: (el) => charts.macroLine(el, series.vix, { name: 'VIX', unit: '', threshold: 30, hex: COLORS.VIXCLS }), empty: !hasPoints(series.vix) },
    dollar: { title: '美元环境', sub: '广义美元指数 · 近 5 年', render: (el) => charts.macroLine(el, series.dollar, { name: '美元指数', unit: '', hex: COLORS.DTWEXBGS }), empty: !hasPoints(series.dollar) },
  };

  const chartBody = (key, emptyText = 'FRED 暂未返回该序列。') => panels[key].empty ? ui.emptyState('暂无数据', emptyText) : `<div class="chart" data-macro="${key}" style="height:222px"></div>`;

  root.innerHTML = `<section class="view">
    ${viewHead({ eyebrow: meta.eyebrow, title: '宏观雷达', sub: '从经济周期、利率、通胀、就业、信用与流动性，观察美国宏观环境的变化。', actions: asOfBadge(data.as_of, '数据截至') })}
    <div class="macro-weather">${weather}</div>
    <div class="macro-cards">${cards.map(macroCard).join('')}</div>
    ${fomcSection(data)}
    ${sectionHead('周期与风险', '环境象限、期限结构与独立衰退观察规则')}
    <div class="macro-focus-grid">
      <section class="panel macro-cycle-panel">
        <div class="panel-head"><div class="panel-title">经济周期象限 <span class="sub">CFNAI 3M × 核心 CPI 同比 · 近 36 个月</span></div></div>
        <div class="panel-body">${cycleTrail.length || cycleCurrent
          ? `<div class="macro-cycle-grid"><div class="chart" data-macro="cycle" style="height:300px"></div><aside class="macro-cycle-side"><span class="macro-kicker">当前环境</span><strong>${esc(cycle.label || '—')}</strong><p>${esc(cycle.detail || '数据不足以定位周期。')}</p><dl><div><dt>增长动能</dt><dd>${fmtNum(cycleCurrent?.x, 2)}</dd></div><div><dt>核心通胀</dt><dd>${fmtNum(cycleCurrent?.y, 2)}%</dd></div><div><dt>观测期</dt><dd>${esc(cycleCurrent?.date || cycle.as_of || '—')}</dd></div></dl></aside></div>`
          : ui.emptyState('周期数据不足', 'CFNAI 或核心 CPI 历史尚未达到最少窗口。')}</div>
      </section>
      <section class="panel"><div class="panel-head"><div class="panel-title">衰退观察 <span class="sub">独立规则，不是综合评分或概率</span></div></div><div class="panel-body">${recessionWatch(data.recession_watch)}</div></section>
    </div>
    ${sectionHead('利率与通胀', '期限结构、实际利率与通胀补偿')}
    <div class="macro-grid">
      ${panel({ title: panels['yield-curve'].title, sub: panels['yield-curve'].sub, body: chartBody('yield-curve') })}
      ${panel({ title: panels.inflation.title, sub: panels.inflation.sub, body: panels.inflation.empty ? ui.emptyState('暂无数据', 'FRED 暂未返回通胀数据。') : `${chips ? `<div class="macro-metric-pills">${chips}</div>` : ''}<div class="chart" data-macro="inflation" style="height:202px"></div>` })}
      ${panel({ title: panels['real-rates'].title, sub: panels['real-rates'].sub, body: chartBody('real-rates') })}
      ${panel({ title: panels.yields.title, sub: panels.yields.sub, body: chartBody('yields') })}
    </div>
    ${sectionHead('就业与增长', '劳动力市场流量、增长与住房领先指标')}
    <div class="macro-grid">
      ${panel({ title: panels.labor.title, sub: panels.labor.sub, body: chartBody('labor') })}
      ${panel({ title: panels['labor-flows'].title, sub: panels['labor-flows'].sub, body: chartBody('labor-flows') })}
      ${panel({ title: panels.growth.title, sub: panels.growth.sub, body: chartBody('growth') })}
    </div>
    ${sectionHead('信用、流动性与市场', '风险补偿、金融条件与货币环境')}
    <div class="macro-grid">
      ${panel({ title: panels.credit.title, sub: panels.credit.sub, body: chartBody('credit') })}
      ${panel({ title: panels.nfci.title, sub: panels.nfci.sub, body: chartBody('nfci') })}
      ${panel({ title: panels.liquidity.title, sub: panels.liquidity.sub, body: chartBody('liquidity') })}
      ${panel({ title: panels.vix.title, sub: panels.vix.sub, body: chartBody('vix') })}
      ${panel({ title: panels.dollar.title, sub: panels.dollar.sub, body: chartBody('dollar') })}
    </div>
    <details class="macro-method">
      <summary>方法与局限 <span>宏观指标不是预测器</span></summary>
      <div>
        <p>期限利差采用 10Y-2Y 与 10Y-3M 的即期差值；倒挂是历史上较早的经济预警信号，但领先期不稳定，也可能出现假信号。Sahm 规则以三个月失业率均值相对前 12 个月低点上升 0.50 个百分点为观察阈值；此处按 FRED 失业率序列近似计算。</p>
        <p>CFNAI 为芝加哥联储全国活动指数，三个月均值低于 -0.7 通常表示衰退风险上升；新屋许可、初请失业金与信用利差属于不同频率和发布时滞的指标。NFCI 负值表示金融条件相对宽松，高收益债 OAS 是风险补偿而非违约概率。FRED 对高收益 OAS 仅保留约 3 年窗口，长历史信用环境参考 Baa-10Y 利差；两者评级范围不同，不可直接拼接。周期象限按增长与通胀水平分类，仅用于组织信息。</p>
        <p>数据来自 FRED。部分序列有发布延迟或修订，最新值可能随后调整；这些规则不构成投资建议。<a href="https://www.newyorkfed.org/medialibrary/media/research/current_issues/ci2-7.pdf" target="_blank" rel="noopener noreferrer">Estrella &amp; Mishkin 期限利差研究</a> · <a href="https://fred.stlouisfed.org/series/SAHMREALTIME" target="_blank" rel="noopener noreferrer">Sahm 规则</a> · <a href="https://www.chicagofed.org/research/data/cfnai/current-data" target="_blank" rel="noopener noreferrer">CFNAI 说明</a></p>
      </div>
    </details>
    <section class="panel macro-explorer">
      <div class="panel-head"><div class="panel-title">宏观序列浏览器 <span class="sub">点击上方指标卡片可快速定位</span></div><div class="panel-actions explorer-controls">
        <select class="input" data-series-select aria-label="选择宏观序列">${seriesOptions(state.seriesId)}</select>
        <select class="input" data-years-select aria-label="选择时间跨度">${YEARS.map((year) => `<option value="${year}" ${year === state.years ? 'selected' : ''}>${year} 年</option>`).join('')}</select>
      </div></div>
      <div class="chart-meta" data-explorer-meta>正在读取 ${esc(SERIES_MAP[state.seriesId].label)}…</div>
      <div class="chart-body"><div class="chart" data-explorer style="height:340px"></div></div>
    </section>
  </section>`;

  Object.entries(panels).forEach(([key, item]) => {
    if (item.empty) return;
    const el = $(`[data-macro="${key}"]`, root);
    if (el) item.render(el);
  });
  if (cycleTrail.length || cycleCurrent) {
    charts.macroQuadrant($('[data-macro="cycle"]', root), { trail: cycleTrail, current: cycleCurrent, thresholds: cycle.thresholds || { growth: 0, inflation: 2 } });
  }
  const corridorEl = $('[data-fomc-corridor]', root);
  if (corridorEl) {
    const corridor = data.series?.policy_corridor || {};
    const groups = [
      { name: '目标上限', points: corridor.target_upper, step: true },
      { name: '目标下限', points: corridor.target_lower, step: true, dashed: true },
      { name: 'EFFR', points: corridor.effective },
      { name: 'SOFR', points: corridor.sofr, dashed: true },
    ].filter((group) => hasPoints(group.points));
    if (groups.length) charts.macroMultiLine(corridorEl, groups, { unit: '%' });
    else corridorEl.innerHTML = ui.emptyState('暂无政策走廊序列', 'FRED 暂未返回目标区间或短端利率数据。');
  }

  const explorerEl = $('[data-explorer]', root);
  const explorerMeta = $('[data-explorer-meta]', root);
  const seriesSelect = $('[data-series-select]', root);
  const yearsSelect = $('[data-years-select]', root);

  function paintExplorer(payload) {
    if (!payload) {
      explorerEl.innerHTML = ui.emptyState('序列不可用', 'FRED 暂时无法返回该序列，请稍后重试。');
      explorerMeta.innerHTML = '<span class="neg">宏观序列加载失败</span>';
      return;
    }
    const points = payload.points || [];
    if (!points.length) {
      explorerEl.innerHTML = ui.emptyState('暂无观测', '该序列在所选时间范围内没有可用数据。');
      explorerMeta.textContent = `${payload.label} · ${payload.freq} · 暂无观测`;
      return;
    }
    const latest = points[points.length - 1];
    explorerMeta.innerHTML = `${esc(payload.label)} · 最新 <b>${fmtNum(latest.v, 2)}${esc(payload.unit || '')}</b> · ${points.length} 个观测 · 截至 ${esc(latest.d)}${payload.yoy ? ' · 同比口径' : ''}`;
    explorerEl.innerHTML = '';
    charts.macroLine(explorerEl, points, { name: payload.label, unit: payload.unit || '', threshold: THRESHOLDS[payload.id] ?? null, hex: COLORS[payload.id] || null });
  }

  async function loadSeries(id, { scroll = false } = {}) {
    const info = SERIES_MAP[id];
    if (!info) return;
    state.seriesId = id;
    if (seriesSelect.value !== id) seriesSelect.value = id;
    const token = ++state.seriesToken;
    explorerMeta.innerHTML = `<span class="spinner" style="width:12px;height:12px;border-width:1.5px"></span><span>正在读取 ${esc(info.label)}…</span>`;
    try {
      const payload = await api.get(`/api/macro/series/${encodeURIComponent(id)}?years=${state.years}`, { signal, timeout: 60000 });
      if (token !== state.seriesToken || !isActive() || state.disposed) return;
      paintExplorer(payload);
    } catch (error) {
      if (error?.name === 'AbortError' || state.disposed || token !== state.seriesToken) return;
      paintExplorer(null);
      explorerMeta.innerHTML = `<span class="neg">${esc(error.message || '序列加载失败')}</span>`;
    }
    if (scroll) {
      const explorer = $('.macro-explorer', root);
      if (explorer) window.scrollTo({ top: explorer.getBoundingClientRect().top + window.scrollY - 84, behavior: 'smooth' });
    }
    try { history.replaceState(null, '', id ? `#/macro?series=${encodeURIComponent(id)}` : '#/macro'); } catch { /* ignore */ }
  }

  paintExplorer(initialExplorer);
  seriesSelect.addEventListener('change', () => loadSeries(seriesSelect.value));
  yearsSelect.addEventListener('change', () => { state.years = Number(yearsSelect.value) || 10; loadSeries(state.seriesId); });
  root.addEventListener('click', (event) => {
    const card = event.target.closest('[data-series]');
    if (card) loadSeries(card.dataset.series, { scroll: true });
  });

  return () => { state.disposed = true; state.seriesToken += 1; };
}
