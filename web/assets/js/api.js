export class ApiError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

const GET_CACHE = new Map();
const GET_CACHE_LIMIT = 32;

function cacheTtl(path) {
  const pathname = String(path || '').split('?')[0];
  if (pathname === '/api/screener/presets') return 10 * 60 * 1000;
  if (pathname === '/api/macro/overview') return 120 * 1000;
  if (pathname === '/api/market/overview') return 20 * 1000;
  if (pathname === '/api/screener/universe') return 120 * 1000;
  if (pathname === '/api/market/earnings') return 60 * 1000;
  if (pathname === '/api/quotes') return 5 * 1000;
  if (pathname === '/api/watchlist/analyze') return 30 * 1000;
  if (pathname.startsWith('/api/compare')) return 30 * 1000;
  if (pathname.startsWith('/api/funds') || pathname.startsWith('/api/fund')) return 120 * 1000;
  if (pathname.startsWith('/api/stocks/')) {
    if (pathname.endsWith('/mda')) return 5 * 60 * 1000;
    if (pathname.endsWith('/statements')) return 2 * 60 * 1000;
    if (pathname.endsWith('/cashflow')) return 2 * 60 * 1000;
    if (pathname.endsWith('/overview')) return 15 * 1000;
    if (pathname.endsWith('/chart')) return 15 * 1000;
  }
  return 0;
}

function remember(path, data, ttl) {
  if (!ttl) return;
  if (Array.isArray(data?.errors) && data.errors.length) return;
  if (GET_CACHE.size >= GET_CACHE_LIMIT) {
    const oldest = GET_CACHE.keys().next().value;
    GET_CACHE.delete(oldest);
  }
  GET_CACHE.set(path, { expires: Date.now() + ttl, data });
}

async function request(path, { method = 'GET', body, signal, timeout = 120000 } = {}) {
  const ttl = method === 'GET' ? cacheTtl(path) : 0;
  if (ttl) {
    const hit = GET_CACHE.get(path);
    if (hit && hit.expires > Date.now()) return hit.data;
    if (hit) GET_CACHE.delete(path);
  }

  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeout);
  const onAbort = () => controller.abort();
  if (signal) {
    if (signal.aborted) controller.abort();
    else signal.addEventListener('abort', onAbort, { once: true });
  }
  try {
    const response = await fetch(path, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
      cache: 'no-store',
    });
    if (!response.ok) {
      let detail = '';
      try {
        const payload = await response.json();
        detail = typeof payload?.detail === 'string' ? payload.detail : JSON.stringify(payload?.detail || '');
      } catch {
        /* ignore malformed errors */
      }
      throw new ApiError(detail || `请求失败（HTTP ${response.status}）`, response.status);
    }
    const data = await response.json();
    remember(path, data, ttl);
    return data;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error?.name === 'AbortError') {
      if (timedOut) throw new ApiError('请求超时，上游数据源响应较慢，请稍后重试');
      throw error;
    }
    if (error instanceof TypeError) {
      throw new ApiError('无法连接后端服务，请确认本地服务已启动');
    }
    throw error;
  } finally {
    clearTimeout(timer);
    if (signal) signal.removeEventListener('abort', onAbort);
  }
}

export const api = {
  get(path, options) {
    return request(path, options);
  },
  post(path, body, options = {}) {
    return request(path, { ...options, method: 'POST', body });
  },
};
