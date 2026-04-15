import axios, { type AxiosRequestConfig } from 'axios'
import { TOKEN_KEY } from '@/lib/constants'
import { useAuthStore } from '@/store/authStore'
import type { SignalsResponse, SignalFilters, DailyStats, ScanTodayRecord } from '@/types/signal'
import type { WatchlistItem, WatchlistResponse, WatchlistAddRequest } from '@/types/watchlist'
import type { ScansResponse } from '@/types/scan'
import type { LoginRequest, LoginResponse, OtpVerifyRequest, AuthResponse } from '@/types/auth'
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
  timeout: 8_000,
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

let isRefreshing = false
let refreshPromise: Promise<string | null> | null = null
let isRedirecting = false

// Nuclear failsafe: if we see 3+ 401s within 5 seconds, force logout.
// This catches the edge case where the refresh "succeeds" but the new
// token is immediately rejected — creating an infinite 401 loop that
// the normal interceptor logic can't break.
let _401count = 0
let _401windowStart = 0
const _401_MAX = 3
const _401_WINDOW_MS = 5000

async function silentRefresh(): Promise<string | null> {
  const token = typeof window !== 'undefined' ? localStorage.getItem(TOKEN_KEY) : null
  if (!token) return null
  try {
    const res = await axios.post<AuthResponse>(
      `${API_URL}/auth/refresh`,
      {},
      { headers: { Authorization: `Bearer ${token}` } },
    )
    const newToken = res.data.access_token
    if (!newToken) return null
    localStorage.setItem(TOKEN_KEY, newToken)
    document.cookie = `${TOKEN_KEY}=${newToken}; path=/; max-age=86400; SameSite=Strict`
    return newToken
  } catch {
    return null
  }
}

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
      // Nuclear failsafe: too many 401s too fast = something is broken, just logout
      const now401 = Date.now()
      if (now401 - _401windowStart > _401_WINDOW_MS) {
        _401count = 0
        _401windowStart = now401
      }
      _401count++
      if (_401count >= _401_MAX) {
        forceLogout('expired')
        return new Promise(() => {})
      }

      // Skip refresh on auth routes (login/verify) -- those 401s are user-facing
      const isAuthRoute = PUBLIC_ROUTES.some((r) => error.config.url?.startsWith(r))
      if (isAuthRoute) {
        const rawDetail = error.response.data?.detail || error.message
        throw new Error(rawDetail)
      }

      // If we already retried this request once and got 401 again, the new
      // token is also bad. Force logout immediately — do NOT fall through to
      // the generic error handler (the previous bug: this case threw a regular
      // error which React Query swallowed, leaving the user stuck on the page).
      if (error.config._retried) {
        forceLogout('expired')
        return new Promise(() => {})
      }

      // First 401 for this request — try silent refresh before logging out.
      // Coalesce concurrent refreshes so parallel 401s share one refresh call.
      if (!isRefreshing) {
        isRefreshing = true
        refreshPromise = silentRefresh()
      }
      const newToken = await refreshPromise
      isRefreshing = false
      refreshPromise = null

      if (newToken) {
        error.config._retried = true
        error.config.headers.Authorization = `Bearer ${newToken}`
        return client.request(error.config)
      }

      // Refresh failed -- force logout immediately
      forceLogout('expired')
      return new Promise(() => {}) // Kill this request chain
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

// Health (public)
export const healthApi = {
  check: () => get<{ status: string; app: string; uptime_seconds: number; scheduler_running: boolean }>('/health'),
}
