export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

export function isNum(value) {
  return value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));
}

export function num(value) {
  return isNum(value) ? Number(value) : null;
}

export function esc(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

export function safeUrl(url) {
  const text = String(url || '').trim();
  return /^https?:\/\//i.test(text) ? text : '';
}

export function fmtNum(value, digits = 2) {
  if (!isNum(value)) return '—';
  return Number(value).toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function fmtInt(value) {
  if (!isNum(value)) return '—';
  return Math.round(Number(value)).toLocaleString('en-US');
}

export function fmtPct(value, digits = 2, signed = true) {
  if (!isNum(value)) return '—';
  const number = Number(value);
  const sign = signed && number > 0 ? '+' : '';
  return `${sign}${number.toFixed(digits)}%`;
}

export function fmtPrice(value) {
  if (!isNum(value)) return '—';
  const number = Number(value);
  const digits = Math.abs(number) < 1 ? 4 : 2;
  return number.toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function fmtMoney(value, digits = 2) {
  if (!isNum(value)) return '—';
  return `$${Number(value).toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
}

export function fmtMoneyCompact(value, digits = 1) {
  if (!isNum(value)) return '—';
  const number = Number(value);
  const abs = Math.abs(number);
  const sign = number < 0 ? '-' : '';
  const compact = (unit, label) => {
    const valueText = (abs / unit).toFixed(digits).replace(/\.0+$/, '');
    const formatted = Number(valueText).toLocaleString('en-US', { maximumFractionDigits: digits });
    return `${sign}${formatted} ${label}`;
  };
  if (abs >= 1e12) return compact(1e12, '万亿美元');
  if (abs >= 1e8) return compact(1e8, '亿美元');
  if (abs >= 1e4) return compact(1e4, '万美元');
  return `${sign}${abs.toLocaleString('en-US', { maximumFractionDigits: 2 })} 美元`;
}

export function fmtSignedMoney(value, digits = 2) {
  if (!isNum(value)) return '—';
  const number = Number(value);
  const prefix = number > 0 ? '+' : number < 0 ? '-' : '';
  return `${prefix}$${Math.abs(number).toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
}

export function fmtCompact(value, digits = 2) {
  if (!isNum(value)) return '—';
  const number = Number(value);
  const abs = Math.abs(number);
  const sign = number < 0 ? '-' : '';
  if (abs >= 1e12) return `${sign}${(abs / 1e12).toFixed(digits)} 万亿`;
  if (abs >= 1e8) return `${sign}${(abs / 1e8).toFixed(digits)} 亿`;
  if (abs >= 1e4) return `${sign}${(abs / 1e4).toFixed(digits)} 万`;
  return `${sign}${abs.toLocaleString('en-US', { maximumFractionDigits: digits })}`;
}

export function fmtShares(value) {
  if (!isNum(value)) return '—';
  return `${fmtCompact(value, 2)} 股`;
}

export function fmtThousands(value) {
  if (!isNum(value)) return '—';
  return fmtCompact(value, 1);
}

export function fmtDate(value, mode = 'medium') {
  const text = String(value || '');
  if (!text) return '—';
  const datePart = text.length >= 10 ? text.slice(0, 10) : text;
  if (mode === 'short') return datePart.slice(5);
  if (mode === 'year') return datePart.slice(0, 4);
  if (mode === 'month') return datePart.slice(0, 7);
  if (mode === 'full') {
    const time = text.includes('T') ? text.slice(11, 16) : text.length >= 16 ? text.slice(11, 16) : '';
    return time ? `${datePart} ${time}` : datePart;
  }
  return datePart;
}

export function fmtNewsTime(value) {
  const text = String(value || '');
  if (!text) return '—';
  if (text.includes(' ')) return text.slice(5, 16);
  return fmtDate(text, 'short');
}

export function fmtAsOf(value) {
  const text = String(value || '');
  if (!text) return '—';
  if (text.includes('T')) return `ET ${text.slice(11, 16)}`;
  return text;
}

export function todayET() {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/New_York',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date());
}

export function nowET() {
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: 'America/New_York',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(new Date());
}

export function todayCn() {
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'America/New_York',
    month: 'long',
    day: 'numeric',
    weekday: 'short',
  }).format(new Date());
}

export function tone(value) {
  if (!isNum(value)) return 'flat';
  const number = Number(value);
  return number > 0 ? 'pos' : number < 0 ? 'neg' : 'flat';
}

export function toneOf(value) {
  if (!isNum(value)) return 'neutral';
  const number = Number(value);
  return number > 0 ? 'positive' : number < 0 ? 'negative' : 'neutral';
}

export function clamp(value, low, high) {
  return Math.min(high, Math.max(low, value));
}

export function debounce(fn, wait = 200) {
  let timer = null;
  const wrapped = (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), wait);
  };
  wrapped.cancel = () => clearTimeout(timer);
  return wrapped;
}

export function uniq(list) {
  return Array.from(new Set(list));
}

export function sum(list) {
  return list.reduce((total, value) => total + (isNum(value) ? Number(value) : 0), 0);
}

export function downloadCSV(filename, rows) {
  const content = '\uFEFF' + rows
    .map((row) => row
      .map((cell) => {
        const text = cell === null || cell === undefined ? '' : String(cell);
        return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
      })
      .join(','))
    .join('\n');
  const blob = new Blob([content], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function cssVar(name, fallback = '') {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

export function hexToRgba(hex, alpha = 1) {
  const text = String(hex || '').replace('#', '').trim();
  if (text.length !== 6) return `rgba(90, 209, 255, ${alpha})`;
  const value = parseInt(text, 16);
  const r = (value >> 16) & 255;
  const g = (value >> 8) & 255;
  const b = value & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

export function formatRangeValue(value, decimals = 2, unit = '') {
  if (!isNum(value)) return '—';
  return `${Number(value).toFixed(decimals)}${unit}`;
}

export function groupBy(list, keyFn) {
  const map = new Map();
  for (const item of list) {
    const key = keyFn(item);
    if (!map.has(key)) map.set(key, []);
    map.get(key).push(item);
  }
  return map;
}
