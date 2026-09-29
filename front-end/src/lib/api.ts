import axios, { type AxiosRequestConfig } from 'axios'
import { TOKEN_KEY } from '@/lib/constants'
import { useAuthStore } from '@/store/authStore'
import type { SignalsResponse, SignalFilters, DailyStats, ScanTodayRecord } from '@/types/signal'
import type { WatchlistItem, WatchlistResponse, WatchlistAddRequest } from '@/types/watchlist'
import type { ScansResponse } from '@/types/scan'
import type { TodayInsights, PerformanceInsights, BacktestInsights, SignalTrail, SignalVerdict } from '@/types/insights'
import type { CheckJob, CheckMode, CompareJob } from '@/types/check'
import type { SymbolSearchResponse } from '@/types/symbols'
import type { LoginRequest, LoginResponse, OtpVerifyRequest, AuthResponse } from '@/types/auth'
import type {
  AllocateResponse, Holding, HoldingPatch, HoldingsResponse, HoldingUpsertItem, ResolveResponse, ReviewJob,
} from '@/types/holdings'
import type {
  PortfolioItem,
  PortfolioResponse,
  PortfolioAddRequest,
  PortfolioUpdateRequest,
  Position,
  PositionsResponse,
  PositionOpenRequest,
  PositionUpdateRequest,
  PositionCloseRequest,
} from '@/types/portfolio'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1'

const PUBLIC_ROUTES = ['/auth/login', '/auth/verify-otp']
const PUBLIC_EXACT = ['/health']

export const client = axios.create({
  baseURL: API_URL,
  timeout: 15_000,
  headers: { 'Content-Type': 'application/json' },
})

/** Sanitize error detail — strip stack traces but keep auth messages */
function sanitizeErrorMessage(status: number, raw: string | undefined): string {
  if (status >= 500) return 'Something went wrong — please try again later.'
  if (!raw) return 'Request failed.'
  // Keep auth error messages as-is (they're user-facing from the backend)
  if (status === 401 || status === 429) return raw
  // Strip anything that looks like a file path or stack trace
  if (/\/(app|usr|home|var|node_modules)\//i.test(raw) || /Traceback|File "/i.test(raw)) {
    return 'Request failed — invalid input.'
  }
  // Keep 400 validation details (they're user-facing) but cap length
  if (raw.length > 300) return raw.slice(0, 300) + '...'
  return raw
}

client.interceptors.request.use((config) => {
  // Already logging out — kill ALL new requests before they reach the server.
  // This stops the 401 flood from React Query refetchInterval hooks that keep
  // firing during the ~100ms between forceLogout() and the actual browser
  // navigation to /login.
  if (isRedirecting) {
    return Promise.reject(new Error('Logging out'))
  }
  const isPublic = PUBLIC_ROUTES.some((r) => config.url?.startsWith(r)) || PUBLIC_EXACT.some((r) => config.url === r)
  if (!isPublic) {
    const token = typeof window !== 'undefined' ? localStorage.getItem(TOKEN_KEY) : null
    if (!token) {
      forceLogout()
      return Promise.reject(new Error('Not authenticated'))
    }
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Module-level guard so that once forceLogout is in flight, every
// subsequent request and response is killed instead of generating more
// 401s while the browser navigates. See response interceptor below.
let isRedirecting = false

/**
 * Atomically clear all auth state and hard-redirect to /login.
 *
 * Clears:
 *   - localStorage token (so api.ts request interceptor sees no token)
 *   - cookie (so middleware sees no token on next navigation)
 *   - Zustand auth store (so React components re-render as logged-out)
 *
 * Then performs a hard navigation via window.location.replace() so the
 * browser doesn't preserve any cached React state from the previous page.
 *
 * Idempotent: subsequent calls are no-ops thanks to the isRedirecting guard,
 * which also makes the response interceptor swallow any in-flight 401 storm
 * so we don't navigate twice.
 */
function forceLogout(reason: 'expired' | 'invalid' = 'expired') {
  if (isRedirecting || typeof window === 'undefined') return
  isRedirecting = true

  // 1. Clear localStorage
  try {
    localStorage.removeItem(TOKEN_KEY)
  } catch {
    // ignore
  }

  // 2. Clear cookie (must match path used when setting it)
  try {
    document.cookie = `${TOKEN_KEY}=; path=/; max-age=0; SameSite=Strict`
    // Belt and suspenders: also try the legacy expires format for older browsers
    document.cookie = `${TOKEN_KEY}=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT`
  } catch {
    // ignore
  }

  // 3. Clear Zustand state synchronously so React components re-render as
  // logged-out before the navigation. authStore has no dependency on api.ts
  // so the static import at the top of this file doesn't create a cycle.
  try {
    useAuthStore.getState().logout()
  } catch {
    // store unavailable — the hard redirect below will fix it anyway
  }

  // 4. Hard redirect — replace() instead of href so the broken page isn't in
  // history. The reason query param is read by /login to show a toast.
  window.location.replace(`/login?reason=${reason}`)
}

client.interceptors.response.use(
  (response) => response,
  async (error) => {
    // Cancelled requests (AbortController) -- rethrow silently
    if (axios.isCancel(error)) throw error

    // Already redirecting -- swallow all errors to stop the 401 storm
    if (isRedirecting) {
      return new Promise(() => {}) // Never resolves -- kills pending requests
    }

    if (error.response?.status === 401 && error.config) {
      // Skip on auth routes (login/verify-otp) — those 401s are user-facing
      // messages like "wrong password" that the form needs to render.
      const isAuthRoute = PUBLIC_ROUTES.some((r) => error.config.url?.startsWith(r))
      if (isAuthRoute) {
        const rawDetail = error.response.data?.detail || error.message
        throw new Error(rawDetail)
      }

      // Day-32 (May 12): simplified — any 401 on a protected route boots
      // to /login immediately. The prior silent-refresh path had edge
      // cases (refresh "succeeds" with a token the backend re-rejects;
      // concurrent React Query refetches racing each other) that left
      // the user stuck on a broken page with 401s flooding the backend
      // for minutes. Logging out is recoverable in 5 seconds; a frozen
      // page wasting API quota is not.
      // The nuclear-failsafe / _retried / silentRefresh complexity is
      // gone — if you see this comment and the backend's /auth/refresh
      // is reliable, you can reintroduce it, but pair it with a real
      // integration test that proves the redirect always fires.
      forceLogout('expired')
      return new Promise(() => {}) // Kill this request chain — caller never resolves
    }

    if (error.response?.status === 403) {
      throw new Error('Access denied.')
    }

    if (error.response?.status === 429) {
      throw new Error('Too many requests — please wait a moment.')
    }

    if (!error.response) {
      throw new Error('Network error — please check your connection.')
    }

    const status = error.response.status as number
    const rawDetail = error.response.data?.detail || error.message
    throw new Error(sanitizeErrorMessage(status, rawDetail))
  }
)

/**
 * Create an AbortController wired to an API call.
 * Usage in useEffect:
 *   const { signal, abort } = createAbortableRequest()
 *   get('/foo', {}, { signal })
 *   return () => abort()
 */
export function createAbortableRequest() {
  const controller = new AbortController()
  return { signal: controller.signal, abort: () => controller.abort() }
}

async function get<T>(url: string, params?: Record<string, unknown>, extra?: AxiosRequestConfig): Promise<T> {
  const config: AxiosRequestConfig = { ...extra, ...(params ? { params } : {}) }
  const res = await client.get<T>(url, config)
  return res.data
}

async function post<T>(url: string, data?: unknown, extra?: AxiosRequestConfig): Promise<T> {
  const res = await client.post<T>(url, data, extra)
  return res.data
}

async function put<T>(url: string, data?: unknown, extra?: AxiosRequestConfig): Promise<T> {
  const res = await client.put<T>(url, data, extra)
  return res.data
}

async function del<T>(url: string, extra?: AxiosRequestConfig): Promise<T> {
  const res = await client.delete<T>(url, extra)
  return res.data
}

// Auth
export const authApi = {
  login: (body: LoginRequest) => post<LoginResponse>('/auth/login', body),
  verifyOtp: (body: OtpVerifyRequest) => post<AuthResponse>('/auth/verify-otp', body),
  logout: () => post<{ message: string }>('/auth/logout'),
  refresh: () => post<AuthResponse>('/auth/refresh'),
}

// Signals — backend wraps in { signals, count }
export const signalsApi = {
  getAll: (filters?: SignalFilters) =>
    get<SignalsResponse>('/signals', filters as Record<string, unknown>),
  getGems: (limit?: number) =>
    get<SignalsResponse>('/signals/gems', limit ? { limit } : undefined),
  getByTicker: (ticker: string, limit?: number) =>
    get<SignalsResponse>(`/signals/${ticker}`, limit ? { limit } : undefined),
}

// Watchlist — backend wraps in { items, count }
export const watchlistApi = {
  getAll: () => get<WatchlistResponse>('/watchlist'),
  add: (ticker: string, body?: WatchlistAddRequest) => post<WatchlistItem>(`/watchlist/${ticker}`, body),
  remove: (ticker: string) => del<{ message: string }>(`/watchlist/${ticker}`),
}

// Scans — backend wraps in { scans, count }
export interface ScanProgress {
  scan_id: string
  status: string
  progress_pct: number
  phase: string
  current_ticker: string
  candidates: number
  tickers_scanned: number
  signals_found: number
  gems_found: number
  started_at: string | null
  completed_at: string | null
  error_message: string | null
}

export const scansApi = {
  getAll: (limit?: number) =>
    get<ScansResponse>('/scans', limit ? { limit } : undefined),
  getToday: () => get<ScanTodayRecord[]>('/scans/today'),
  trigger: (scan_type?: string) =>
    post<{ scan_id: string; status: string; message: string }>(
      `/scans/trigger${scan_type ? `?scan_type=${scan_type}` : ''}`,
    ),
  getProgress: (scanId: string) =>
    get<ScanProgress>(`/scans/${scanId}/progress`),
}

// Stats
export const statsApi = {
  getDaily: () => get<DailyStats>('/stats/daily'),
}

// Portfolio
export const portfolioApi = {
  getAll: () => get<PortfolioResponse>('/portfolio'),
  add: (body: PortfolioAddRequest) => post<PortfolioItem>('/portfolio', body),
  update: (id: string, body: PortfolioUpdateRequest) => put<PortfolioItem>(`/portfolio/${id}`, body),
  remove: (id: string) => del<{ message: string }>(`/portfolio/${id}`),
}

// Positions
export const positionsApi = {
  getOpen: () => get<PositionsResponse>('/positions'),
  getHistory: (limit?: number) =>
    get<PositionsResponse>('/positions/history', limit ? { limit } : undefined),
  getById: (id: string) => get<Position>(`/positions/${id}`),
  open: (body: PositionOpenRequest) => post<Position>('/positions', body),
  update: (id: string, body: PositionUpdateRequest) => put<Position>(`/positions/${id}`, body),
  close: (id: string, body: PositionCloseRequest) => post<Position>(`/positions/${id}/close`, body),
}

// Tickers — detail + chart data
export interface TickerDetail {
  ticker: string
  name: string
  company_name: string | null
  exchange: string
  asset_type: string | null
  sector: string | null
  industry: string | null
  market_cap: number | null
  pe_ratio: number | null
  eps: number | null
  dividend_yield: number | null
  beta: number | null
  week_52_high: number | null
  week_52_low: number | null
  avg_volume: number | null
  current_price: number | null
  day_change_pct: number | null
  fundamentals: Record<string, unknown> | null
  period_changes?: Record<string, unknown> | null
}

export interface TickerChart {
  ticker: string
  period: string
  timestamps: string[]
  prices: number[]
  volumes: number[]
}

export const tickersApi = {
  getDetail: (ticker: string) =>
    get<TickerDetail>(`/tickers/${ticker}`),
  getChart: (ticker: string, period?: string) =>
    get<TickerChart>(`/tickers/${ticker}/chart`, period ? { period } : undefined),
  getSignals: (ticker: string, limit?: number) =>
    get<SignalsResponse>(`/tickers/${ticker}/signals`, limit ? { limit } : undefined),
}

// Insights — read-only views over scans, decisions, outcomes and backtests
export const insightsApi = {
  getToday: () => get<TodayInsights>('/insights/today'),
  getPerformance: () => get<PerformanceInsights>('/insights/performance'),
  getBacktest: () => get<BacktestInsights>('/insights/backtest'),
  getSignalTrail: (ticker: string) =>
    get<SignalTrail>(`/insights/signal/${encodeURIComponent(ticker)}`),
  getVerdicts: (ids: string[]) =>
    get<{ verdicts: Record<string, SignalVerdict> }>('/insights/verdicts', { ids: ids.join(',') }),
}

// Health (public)
// Check a stock — 4xx responses carry {detail: {code, message}}; they are
// returned (not thrown by the interceptor) so the page can show a friendly,
// translated error per code. 401 still goes through the interceptor.
export class CheckApiError extends Error {
  code: string
  status: number
  /** the rest of the {detail} object (e.g. compare: symbols / inputs / needed) */
  extra: Record<string, unknown>
  constructor(code: string, message: string, status: number, extra: Record<string, unknown> = {}) {
    super(message)
    this.code = code
    this.status = status
    this.extra = extra
  }
}

async function checkCall<T>(method: 'get' | 'post', url: string, data?: unknown): Promise<T> {
  const res = await client.request<T | { detail?: unknown }>({
    method,
    url,
    data,
    validateStatus: (s) => (s >= 200 && s < 300) || s === 400 || s === 404 || s === 422 || s === 429,
  })
  if (res.status >= 400) {
    const detail = (res.data as { detail?: unknown } | undefined)?.detail
    const obj = detail && typeof detail === 'object' ? (detail as { code?: string; message?: string }) : null
    const code = obj?.code
      ?? (res.status === 429 ? 'rate_limited' : res.status === 404 ? 'job_not_found' : res.status === 400 ? 'invalid_ticker' : 'internal')
    const message = obj?.message ?? (typeof detail === 'string' ? detail : 'Request failed.')
    throw new CheckApiError(code, message, res.status, obj && !Array.isArray(obj) ? { ...obj } : {})
  }
  return res.data as T
}

export const checkApi = {
  start: (ticker: string, force = false, mode: CheckMode = 'short') =>
    checkCall<CheckJob>('post', '/check', { ticker, force, mode }),
  get: (jobId: string) => checkCall<CheckJob>('get', `/check/${encodeURIComponent(jobId)}`),
  compareStart: (tickers: string[], force = false, mode: CheckMode = 'short') =>
    checkCall<CompareJob>('post', '/check/compare', { tickers, force, mode }),
  compareGet: (compareId: string) =>
    checkCall<CompareJob>('get', `/check/compare/${encodeURIComponent(compareId)}`),
}

// Symbol search (ticker or company name, typo tolerant) for the Check box
export const symbolsApi = {
  search: (q: string, limit = 8, signal?: AbortSignal) =>
    get<SymbolSearchResponse>('/symbols/search', { q, limit }, { signal }),
}

// My holdings — coded 4xx/503 errors are returned as CheckApiError (same
// {detail: {code, message}} shape as /check) so the page can translate them.
async function holdingsCall<T>(
  method: 'get' | 'post' | 'patch' | 'delete',
  url: string,
  data?: unknown,
  extra?: AxiosRequestConfig,
): Promise<T> {
  const res = await client.request<T | { detail?: unknown }>({
    method,
    url,
    data,
    ...extra,
    validateStatus: (s) => (s >= 200 && s < 300) || [400, 404, 409, 422, 429, 503].includes(s),
  })
  if (res.status >= 400) {
    const detail = (res.data as { detail?: unknown } | undefined)?.detail
    const obj = detail && typeof detail === 'object' && !Array.isArray(detail)
      ? (detail as { code?: string; message?: string; next_allowed_at?: string })
      : null
    const code = obj?.code ?? (res.status === 422 ? 'invalid_input' : res.status === 429 ? 'rate_limited' : 'internal')
    const message = obj?.message ?? (typeof detail === 'string' ? detail : 'Request failed.')
    const err = new CheckApiError(code, message, res.status) as CheckApiError & { nextAllowedAt?: string }
    if (obj?.next_allowed_at) err.nextAllowedAt = obj.next_allowed_at
    throw err
  }
  return res.data as T
}

export const holdingsApi = {
  list: () => holdingsCall<HoldingsResponse>('get', '/holdings'),
  // Resolving ~30 tickers makes several Yahoo lookups each — allow 90s.
  resolve: (text: string) => holdingsCall<ResolveResponse>('post', '/holdings/resolve', { text }, { timeout: 90_000 }),
  save: (items: HoldingUpsertItem[]) =>
    holdingsCall<{ count: number; created: number; updated: number; refreshing: boolean }>('post', '/holdings', { items }),
  update: (id: string, body: HoldingPatch) =>
    holdingsCall<Holding>('patch', `/holdings/${encodeURIComponent(id)}`, body),
  remove: (id: string) => holdingsCall<{ message: string }>('delete', `/holdings/${encodeURIComponent(id)}`),
  refresh: () => holdingsCall<{ status: 'started' | 'running' }>('post', '/holdings/refresh'),
  review: (body: { ids?: string[]; all?: boolean }) => holdingsCall<ReviewJob>('post', '/holdings/review', body),
  reviewCurrent: () => holdingsCall<{ job: ReviewJob | null }>('get', '/holdings/review/current'),
  reviewJob: (jobId: string) => holdingsCall<ReviewJob>('get', `/holdings/review/${encodeURIComponent(jobId)}`),
  allocate: (includeWatchlist = false) =>
    holdingsCall<AllocateResponse>('get', '/holdings/allocate-ideas', undefined,
      { params: includeWatchlist ? { include_watchlist: true } : undefined, timeout: 45_000 }),
}

export const healthApi = {
  check: () => get<{ status: string; app: string; uptime_seconds: number; scheduler_running: boolean }>('/health'),
}
