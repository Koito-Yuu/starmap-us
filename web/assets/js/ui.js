import { esc } from './utils.js';

export { esc };

const ICONS = {
  search: '<circle cx="11" cy="11" r="6.4"/><path d="M16 16l4.5 4.5"/>',
  refresh: '<path d="M20 11a8 8 0 1 0-2.34 5.66M20 4v7h-7"/>',
  x: '<path d="M6 6l12 12M18 6L6 18"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  minus: '<path d="M5 12h14"/>',
  trash: '<path d="M4 7h16M9 7V5h6v2M6.5 7l.8 13h9.4l.8-13M10 11v5M14 11v5"/>',
  download: '<path d="M12 4v11M7 10l5 5 5-5M4 20h16"/>',
  external: '<path d="M14 4h6v6M20 4l-9 9M18 14v6H4V6h6"/>',
  arrowLeft: '<path d="M19 12H5M11 18l-6-6 6-6"/>',
  arrowUpRight: '<path d="M7 17L17 7M8 7h9v9"/>',
  chevronDown: '<path d="M6 9l6 6 6-6"/>',
  chevronLeft: '<path d="M15 18l-6-6 6-6"/>',
  chevronRight: '<path d="M9 6l6 6-6 6"/>',
  check: '<path d="M4 12.5l5 5L20 6.5"/>',
  alert: '<path d="M12 3L2.5 20h19L12 3z"/><path d="M12 9v5M12 17.2v.3"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 7.5v.3"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/>',
  star: '<path d="M12 3.5l2.7 5.7 6.1.8-4.5 4.3 1.1 6.1-5.4-3-5.4 3 1.1-6.1L3.2 10l6.1-.8z"/>',
  calendar: '<rect x="3.5" y="5" width="17" height="15.5" rx="2.2"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
  newspaper: '<path d="M5 4.5h14a1.5 1.5 0 0 1 1.5 1.5v13.5H5A2.5 2.5 0 0 1 2.5 17V6.5A2 2 0 0 1 4.5 4.5H5z"/><path d="M6 8.5h7M6 12h7M6 15.5h4"/>',
  trendUp: '<path d="M3 17l6-6 4 4 8-8"/><path d="M14 7h7v7"/>',
  trendDown: '<path d="M3 7l6 6 4-4 8 8"/><path d="M14 17h7v-7"/>',
  activity: '<path d="M3 13h4l2.5-7 4 13 2.5-7H21"/>',
  layers: '<path d="M12 3l9 5-9 5-9-5 9-5z"/><path d="M3 12l9 5 9-5M3 16l9 5 9-5"/>',
  file: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4M9 12h6M9 16h6"/>',
  briefcase: '<rect x="3" y="7.5" width="18" height="12.5" rx="2.4"/><path d="M8.5 7.5V6a2 2 0 0 1 2-2h3a2 2 0 0 1 2 2v1.5M3 12.5h18M10.5 12.5v2h3v-2"/>',
  database: '<ellipse cx="12" cy="5.5" rx="8" ry="3"/><path d="M4 5.5v6c0 1.66 3.58 3 8 3s8-1.34 8-3v-6M4 11.5v6c0 1.66 3.58 3 8 3s8-1.34 8-3v-6"/>',
  link: '<path d="M10 13.5a4 4 0 0 0 5.66 0l3-3a4 4 0 0 0-5.66-5.66l-1.5 1.5"/><path d="M14 10.5a4 4 0 0 0-5.66 0l-3 3a4 4 0 0 0 5.66 5.66l1.5-1.5"/>',
  spark: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/>',
  filter: '<path d="M4 6h16M7 12h10M10 18h4"/>',
  sliders: '<path d="M4 7h5M13 7h7M4 17h9M17 17h3"/><circle cx="11" cy="7" r="2"/><circle cx="15" cy="17" r="2"/>',
  grid: '<rect x="3" y="3" width="7.5" height="7.5" rx="1.8"/><rect x="13.5" y="3" width="7.5" height="7.5" rx="1.8"/><rect x="3" y="13.5" width="7.5" height="7.5" rx="1.8"/><rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1.8"/>',
  wallet: '<path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H18v3"/><rect x="3" y="7" width="18" height="12.5" rx="2.2"/><path d="M16 12.5h3v3h-3a1.5 1.5 0 0 1 0-3z"/>',
  compare: '<circle cx="7" cy="7" r="3"/><circle cx="17" cy="17" r="3"/><path d="M10 7h5a2 2 0 0 1 2 2v5M14 17H9a2 2 0 0 1-2-2V9"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.6 2.6 3.8 5.6 3.8 9S14.6 18.4 12 21c-2.6-2.6-3.8-5.6-3.8-9S9.4 5.6 12 3z"/>',
  cpu: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9.5 9.5h5v5h-5zM12 2v4M12 18v4M2 12h4M18 12h4M5 5l1.5 1.5M17.5 17.5L19 19M19 5l-1.5 1.5M6.5 17.5L5 19"/>',
  play: '<path d="M8 5l11 7-11 7z"/>',
};

export function icon(name, size = 16, className = '') {
  const body = ICONS[name] || ICONS.info;
  const filled = name === 'starFilled';
  const actual = filled ? 'star' : name;
  return `<svg class="icon ${className}" width="${size}" height="${size}" viewBox="0 0 24 24" aria-hidden="true" fill="${filled ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round">${ICONS[actual]}</svg>`;
}

export function starIcon(filled, size = 14) {
  return `<svg class="icon" width="${size}" height="${size}" viewBox="0 0 24 24" aria-hidden="true" fill="${filled ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${ICONS.star}</svg>`;
}

export function emptyState(title, message = '', action = '') {
  return `
    <div class="empty-state">
      <div class="empty-icon">${icon('spark', 20)}</div>
      <h3>${esc(title)}</h3>
      ${message ? `<p>${esc(message)}</p>` : ''}
      ${action}
    </div>`;
}

export function errorPanel(message, { title = '数据加载失败', retry = true } = {}) {
  return `
    <div class="error-panel">
      <div class="empty-icon">${icon('alert', 20)}</div>
      <h3>${esc(title)}</h3>
      <p>${esc(message || '上游数据源暂时不可用，请稍后重试。')}</p>
      ${retry ? `<button class="btn small" type="button" data-retry>${icon('refresh', 13)}重试</button>` : ''}
    </div>`;
}

export function bindRetry(root, handler) {
  const button = root.querySelector('[data-retry]');
  if (button) button.addEventListener('click', handler);
}

export function warnBanner(messages) {
  const list = (Array.isArray(messages) ? messages : [messages]).filter(Boolean);
  if (!list.length) return '';
  return `<div class="warn-banner">${icon('alert', 13)}<span>${list.map(esc).join(' · ')}</div>`;
}

export function loadingInline(label = '加载中') {
  return `<div class="loading-inline"><span class="spinner"></span><span>${esc(label)}</span></div>`;
}

export function toast(message, tone = 'info', duration = 3400) {
  const root = document.getElementById('toast-root');
  if (!root) return;
  const host = document.createElement('div');
  host.className = `toast ${tone}`;
  const iconName = tone === 'success' ? 'check' : tone === 'error' ? 'alert' : tone === 'warn' ? 'alert' : 'info';
  host.innerHTML = `<span class="t-icon">${icon(iconName, 15)}</span><span>${esc(message)}</span>`;
  root.appendChild(host);
  setTimeout(() => {
    host.classList.add('leaving');
    setTimeout(() => host.remove(), 260);
  }, duration);
}

export function ratingTone(rating) {
  const text = String(rating || '').toLowerCase();
  if (!text) return 'neutral';
  if (text.includes('strong buy') || text.includes('buy') || text.includes('outperform')) return 'positive';
  if (text.includes('sell') || text.includes('underperform')) return 'negative';
  if (text.includes('hold') || text.includes('neutral')) return 'neutral';
  return 'neutral';
}

export function filingTone(form) {
  const text = String(form || '').toUpperCase();
  if (text.startsWith('10-K') || text.startsWith('20-F') || text.startsWith('40-F')) return 'info';
  if (text.startsWith('10-Q')) return 'positive';
  if (text.startsWith('8-K')) return 'neutral';
  return 'tone-neutral';
}
