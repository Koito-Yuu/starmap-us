import { esc, fmtAsOf, fmtNewsTime, safeUrl } from '../utils.js';
import { emptyState, icon } from '../ui.js';

export function viewHead({ eyebrow = '', title = '', sub = '', actions = '' }) {
  return `
    <div class="view-head">
      <div>
        ${eyebrow ? `<div class="eyebrow">${esc(eyebrow)}</div>` : ''}
        <h2>${esc(title)}</h2>
        ${sub ? `<p class="sub">${esc(sub)}</p>` : ''}
      </div>
      ${actions ? `<div class="head-actions">${actions}</div>` : ''}
    </div>`;
}

export function asOfBadge(value, label = '数据时间') {
  return `<span class="as-of"><span class="dot"></span>${esc(label)} ${esc(fmtAsOf(value))}</span>`;
}

export function statCard({ label, value, sub = '', valueClass = '', extra = '' }) {
  return `
    <div class="stat-card">
      <div class="stat-label"><span>${esc(label)}</span></div>
      <div class="stat-value ${valueClass}">${value}</div>
      ${sub ? `<div class="stat-sub">${esc(sub)}</div>` : ''}
      ${extra}
    </div>`;
}

export function rangeSeg(active, ranges = ['1D', '5D', '1M', '3M', '6M', 'YTD', '1Y', '3Y', '5Y', 'MAX']) {
  return `<div class="seg" data-range-seg>${ranges
    .map((item) => `<button type="button" data-range="${item}" class="${item === active ? 'active' : ''}">${item}</button>`)
    .join('')}</div>`;
}

export function tableEmpty(colspan, message) {
  return `<tr><td class="empty-cell" colspan="${colspan}">${esc(message)}</td></tr>`;
}

export function newsList(items, { limit = 8, emptyTitle = '暂无相关资讯' } = {}) {
  const list = (items || []).slice(0, limit);
  if (!list.length) {
    return emptyState(emptyTitle, '公开数据源暂未返回相关新闻，稍后刷新再试。');
  }
  return `
    <div class="news-list">
      ${list
        .map((item) => {
          const url = safeUrl(item.url);
          const title = esc(item.title || '未命名资讯');
          const titleHtml = url
            ? `<a class="news-title" href="${esc(url)}" target="_blank" rel="noopener noreferrer">${title}</a>`
            : `<span class="news-title">${title}</span>`;
          return `
            <article class="news-item">
              <div class="news-time">${esc(fmtNewsTime(item.date))}</div>
              <div class="news-main">
                ${titleHtml}
                ${item.summary ? `<p class="news-summary">${esc(item.summary)}</p>` : ''}
                <div class="news-meta">
                  <span class="src">${esc(item.media || '东方财富')}</span>
                  ${item.important ? `<span class="badge">重要</span>` : ''}
                  ${url ? `<span>${icon('external', 10)}</span>` : ''}
                </div>
              </div>
            </article>`;
        })
        .join('')}
    </div>`;
}
