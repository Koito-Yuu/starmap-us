import * as ui from '../ui.js';
import { esc, fmtDate, fmtInt, fmtNum } from '../utils.js';

function toneLabel(tone) {
  return tone === 'positive' ? '积极' : tone === 'caution' ? '谨慎' : tone === 'negative' ? '负面' : '中性';
}

function sectionColor(index) {
  return ['var(--accent)', 'var(--violet)', 'var(--gold)', 'var(--series-6)', 'var(--series-5)'][index % 5];
}

function excerpt(text, limit = 360) {
  const value = String(text || '').replace(/\s+/g, ' ').trim();
  if (value.length <= limit) return value;
  const cut = value.slice(0, limit);
  const sentenceEnd = Math.max(
    cut.lastIndexOf('. '),
    cut.lastIndexOf('; '),
    cut.lastIndexOf('。'),
    cut.lastIndexOf('；'),
  );
  if (sentenceEnd >= limit * 0.52) return cut.slice(0, sentenceEnd + 1);
  const space = cut.lastIndexOf(' ');
  return `${cut.slice(0, space > limit * 0.6 ? space : limit).trimEnd()}…`;
}

function renderBrief(mda) {
  const items = (mda.management_brief || []).filter((item) => item?.text).slice(0, 4);
  if (!items.length) return '';
  return `<section class="mda-brief">
    <div class="mda-subhead"><span>管理层摘要</span></div>
    <div class="mda-brief-grid" data-count="${items.length}">
      ${items.map((item) => `
        <article class="mda-brief-card ${esc(item.tone || 'neutral')}">
          <div class="mda-brief-top">
            <span>${esc(item.label || '关键表述')}</span>
            <em>${toneLabel(item.tone)}</em>
          </div>
          <p>${esc(excerpt(item.text, 360))}</p>
          ${item.topic ? `<span class="mda-inline-topic">${esc(item.topic)}</span>` : ''}
        </article>`).join('')}
    </div>
  </section>`;
}

function renderSections(mda) {
  const sections = (mda.sections || []).filter((item) => Number(item.share) > 0);
  if (!sections.length) return '';
  const total = sections.reduce((sum, item) => sum + Number(item.share || 0), 0) || 1;
  return `<section class="mda-analysis-card mda-sections">
    <div class="mda-subhead"><span>章节结构</span><small>按财务披露主题拆分</small></div>
    <div class="mda-section-track" aria-hidden="true">
      ${sections.map((item, index) => `<i style="width:${(Number(item.share) / total) * 100}%;background:${sectionColor(index)}" title="${esc(item.label)} ${fmtNum(item.share, 1)}%"></i>`).join('')}
    </div>
    <div class="mda-section-list">
      ${sections.map((item, index) => `
        <article class="mda-section-row">
          <div class="mda-section-top">
            <span class="mda-section-dot" style="background:${sectionColor(index)}"></span>
            <b>${esc(item.label)}</b>
            <small>${fmtNum(item.share, 1)}% · ${fmtInt(item.words)} 词</small>
            <em class="${esc(item.tone_net > 0.12 ? 'pos' : item.tone_net < -0.12 ? 'neg' : 'flat')}">${esc(item.tone || '中性')}</em>
          </div>
          ${(item.themes || []).length ? `<div class="mda-section-themes">${item.themes.map((theme) => `<span>${esc(theme.label)} ${fmtNum(theme.per10k, 1)}</span>`).join('')}</div>` : ''}
        </article>`).join('')}
    </div>
  </section>`;
}

function renderGuidance(mda) {
  const guidance = mda.guidance || [];
  const outlook = mda.outlook || [];
  if (!guidance.length && !outlook.length) return '';
  const quote = (item) => `<blockquote class="mda-quote ${esc(item.tone || 'neutral')}">${item.topic ? `<span class="mq-topic">${esc(item.topic)}</span>` : ''}${esc(excerpt(item.text, 300))}</blockquote>`;
  const primaryOutlook = outlook.slice(0, 2);
  const extraOutlook = outlook.slice(2);
  return `<section class="mda-analysis-card mda-guidance-col">
    <div class="mda-subhead"><span>前瞻与量化指引</span></div>
    ${guidance.length ? `<div class="mda-guidance-list">${guidance.slice(0, 6).map((item) => `
      <article class="mda-guidance-card">
        <div class="mda-guidance-top">
          <b>${esc(item.metric || '量化指引')}</b>
          ${item.period ? `<span>${esc(item.period)}</span>` : ''}
        </div>
        <div class="mda-guidance-values">${(item.values || []).map((value) => `<em>${esc(value)}</em>`).join('')}</div>
        <p>${esc(excerpt(item.text, 280))}</p>
      </article>`).join('')}</div>` : ''}
    ${primaryOutlook.length ? `<div class="mda-outlook-list">${primaryOutlook.map(quote).join('')}</div>` : ''}
    ${extraOutlook.length ? `<details class="mda-outlook-more"><summary>其余 ${extraOutlook.length} 条前瞻</summary><div class="mda-outlook-list">${extraOutlook.map(quote).join('')}</div></details>` : ''}
  </section>`;
}

function renderTextProfile(mda) {
  const tone = mda.tone || {};
  const stats = mda.stats || {};
  const themes = (mda.themes || []).slice(0, 4);
  const peak = Math.max(tone.positive || 0, tone.negative || 0, tone.uncertainty || 0, 1);
  const themePeak = Math.max(...themes.map((item) => item.per10k), 1);
  const bar = (label, value, color) => `<div class="mda-tone-item">
    <div class="mda-tone-top"><span>${esc(label)}</span><span>${fmtNum(value, 1)}</span></div>
    <div class="mda-tone-track"><div class="mda-tone-fill" style="width:${Math.min(100, Math.max(0, ((value || 0) / peak) * 100))}%;background:${color}"></div></div>
  </div>`;
  return `<section class="mda-insight-card mda-text-profile">
    <div class="mda-subhead"><span>文本画像</span><small>措辞密度与主题强度</small></div>
    <div class="mda-profile-grid">
      <div>
        ${bar('正面措辞', tone.positive, 'var(--up)')}
        ${bar('负面措辞', tone.negative, 'var(--down)')}
        ${bar('不确定性', tone.uncertainty, 'var(--gold)')}
        <div class="mda-profile-stats"><span>${fmtInt(stats.words)} 词 · ${fmtInt(stats.sentences)} 句</span><span>Flesch ${fmtNum(stats.flesch, 1)} · ${esc(stats.flesch_label || '—')}</span></div>
      </div>
      <div class="mda-theme-list">
        ${themes.length ? themes.map((item) => `<div class="mda-theme-row">
          <div><span>${esc(item.label)}</span><b>${fmtNum(item.per10k, 1)}</b></div>
          <div class="mda-theme-track"><i style="width:${Math.max(2, (item.per10k / themePeak) * 100)}%"></i></div>
        </div>`).join('') : '<p class="field-hint">未识别到主题关键词。</p>'}
      </div>
    </div>
  </section>`;
}

function renderDelta(report) {
  const delta = report.delta;
  if (!delta) return '';
  const statements = delta.statements || {};
  const chips = [
    ['净语气', `${delta.tone >= 0 ? '+' : ''}${fmtNum(delta.tone, 3)}`, delta.tone >= 0],
    ['不确定性', `${delta.uncertainty >= 0 ? '+' : ''}${fmtNum(delta.uncertainty, 1)}/万词`, delta.uncertainty <= 0],
    ['句级保留', statements.retained_pct === null || statements.retained_pct === undefined ? '—' : `${fmtNum(statements.retained_pct, 1)}%`, null],
    ['量化指引', `${statements.guidance_prior ?? 0} → ${statements.guidance_current ?? 0}`, (statements.guidance_current || 0) >= (statements.guidance_prior || 0)],
  ];
  const moves = delta.section_moves || [];
  return `<section class="mda-insight-card mda-compare">
    <div class="mda-subhead"><span>较上一份年报</span><small>${esc(delta.prior_form || '')} · ${esc(fmtDate(delta.prior_filed))}</small></div>
    <div class="mda-compare-chips">
      ${chips.map(([label, value, good]) => `<span class="mda-compare-chip"><span>${esc(label)}</span><b class="${good === null ? '' : good ? 'pos' : 'neg'}">${value}</b></span>`).join('')}
    </div>
    ${moves.length ? `<div class="mda-section-moves">${moves.map((move) => `<div><span>${esc(move.label)}</span><div class="mda-section-move-track"><i style="left:${move.delta >= 0 ? 50 : 50 + move.delta}%;width:${Math.abs(move.delta)}%;"></i></div><b>${move.delta >= 0 ? '+' : ''}${fmtNum(move.delta, 1)}pp</b></div>`).join('')}</div>` : ''}
    ${(delta.theme_moves || []).length ? `<div class="mda-topic-moves">${delta.theme_moves.slice(0, 5).map((move) => `<span class="${move.delta >= 0 ? 'up' : 'down'}">${esc(move.label)} ${move.delta >= 0 ? '+' : ''}${fmtNum(move.delta, 1)}</span>`).join('')}</div>` : ''}
    ${(statements.changed || []).length ? `<details class="mda-statement-diff"><summary>改写表述 ${statements.changed.length} 条 <span>${fmtNum(statements.changed[0].similarity, 2)} 相似</span></summary>${statements.changed.map((item) => `<div class="mda-diff-row changed"><span>${esc(item.current?.role_label || '改写')}</span><div><p class="before">${esc(excerpt(item.prior?.text, 260))}</p><p>${esc(excerpt(item.current?.text, 300))}</p></div></div>`).join('')}</details>` : ''}
    ${(statements.added || []).length ? `<details class="mda-statement-diff"><summary>新表述 ${statements.added.length} 条</summary>${statements.added.map((item) => `<div class="mda-diff-row"><span>${esc(item.role_label || item.role || '表述')}</span><p>${esc(excerpt(item.text, 320))}</p></div>`).join('')}</details>` : ''}
    ${(statements.removed || []).length ? `<details class="mda-statement-diff"><summary>减少表述 ${statements.removed.length} 条</summary>${statements.removed.map((item) => `<div class="mda-diff-row removed"><span>${esc(item.role_label || item.role || '表述')}</span><p>${esc(excerpt(item.text, 320))}</p></div>`).join('')}</details>` : ''}
    <p class="mda-compare-note">句级变化基于规范化文本指纹；改写通常同时显示为新增与减少，仅用于定位披露重点，不代表事实变化。</p>
  </section>`;
}

function renderRisks(report) {
  const risk = report.risk;
  const delta = report.risk_delta || {};
  const excerpts = (risk?.excerpts || []).length
    ? risk.excerpts
    : risk?.excerpt
      ? [{ text: risk.excerpt, topic: '风险因素' }]
      : [];
  if (!excerpts.length && !(delta.added || []).length) {
    return '<p class="field-hint mda-risk-empty">本次申报未单独展开风险因素章节。</p>';
  }
  return `<section class="mda-risk-section">
    <div class="mda-subhead"><span>风险因素摘录</span><small>${esc(risk?.label || 'RISK')} · ${excerpts.length} 条</small></div>
    ${(delta.added || []).length ? `<div class="mda-risk-new"><b>较上一份年报新增</b>${delta.added.map((item) => `<p>${esc(excerpt(item.text, 300))}</p>`).join('')}</div>` : ''}
    <div class="mda-risk-list">
      ${excerpts.map((item, index) => `<article class="mda-risk-item"><div class="mri-head"><span class="mri-idx">R${index + 1}</span><span class="mri-topic">${esc(item.topic || '风险')}</span></div><p>${esc(excerpt(item.text, 360))}</p></article>`).join('')}
    </div>
  </section>`;
}

export function renderMdaReport(report, notes, mode = 'annual') {
  if (!report) return ui.emptyState('暂无该口径的文本分析', 'EDGAR 申报窗口内未找到对应报告。');
  const mda = report.mda;
  if (!mda) return ui.emptyState('未提取到 MD&A 章节', '该申报可能采用非标准结构，或原文为 PDF 附件。');
  const href = report.url || report.index_url;
  const stats = mda.stats || {};
  const filteredNotes = (notes || [])
    .map((note) => (typeof note === 'string' ? { text: note, scope: 'all', tone: 'neutral' } : note))
    .filter((note) => !note.scope || note.scope === 'all' || note.scope === mode);
  const sections = renderSections(mda);
  const guidance = renderGuidance(mda);
  const profile = renderTextProfile(mda);
  const comparison = renderDelta(report);
  return `<div class="mda-report">
    <div class="mda-meta">
      <span class="badge">${esc(report.form || '—')}</span>
      <span>申报 ${esc(fmtDate(report.filed))}</span>
      ${report.period ? `<span>报告期 ${esc(fmtDate(report.period))}</span>` : ''}
      <span class="mda-metric-meta">${fmtInt(stats.words)} 词 · ${fmtInt(stats.sentences)} 句 · 均句 ${fmtNum(stats.avg_sentence_words, 1)} 词</span>
      ${href ? `<a class="mda-link" href="${esc(href)}" target="_blank" rel="noopener noreferrer">SEC 原文 ${ui.icon('external', 11)}</a>` : ''}
    </div>
    ${renderBrief(mda)}
    ${sections || guidance ? `<div class="mda-analysis-grid">${sections}${guidance}</div>` : ''}
    ${profile && comparison ? `<div class="mda-secondary-grid">${profile}${comparison}</div>` : profile || comparison}
    ${filteredNotes.length ? `<div class="mda-notes">${filteredNotes.map((note) => `<div class="mda-note ${esc(note.tone || 'neutral')}">${esc(note.text)}</div>`).join('')}</div>` : ''}
    ${renderRisks(report)}
  </div>`;
}
