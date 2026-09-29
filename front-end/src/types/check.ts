// Response shapes for /api/v1/check (back-end/app/api/v1/stock_check.py,
// back-end/app/services/stock_check.py). Unknown values are `null`.
import type { ReasonInfo, SignalTrail } from '@/types/insights'

/** Machine-readable message: the UI renders t.check.<group>[code] with
 *  `params`; `text` is the back-end's English fallback. */
export interface CheckText {
  code: string
  params: Record<string, string | number | null>
  text: string
}

export type CheckVerdict = 'BUY_NOW' | 'WAIT' | 'AVOID'

export type CheckPhase =
  | 'resolving' | 'market_data' | 'filter' | 'sentiment' | 'synthesis' | 'decision' | 'risk' | 'done'

export interface CheckResult {
  input: string
  symbol: string
  exchange: string | null
  name: string | null
  asset_class: 'STOCK' | 'ETF' | 'CRYPTO' | string
  bucket: string | null
  sector: string | null
  currency: string | null
  price: number | null
  market_open: boolean
  market_regime: string | null
  verdict: CheckVerdict
  headline: CheckText
  /** failing gates, most important first */
  reasons: ReasonInfo[]
  what_would_change: CheckText[]
  notes: CheckText[]
  gates: { key: string; ok: boolean | null; severity: 'avoid' | 'wait' }[]
  levels: {
    entry: number | null
    ref_price: number | null
    stop: number | null
    target: number | null
    rr: number | null
    min_rr: number
    source: string | null
    atr: number | null
  }
  size: {
    shares: number
    alloc_usd: number | null
    risk_usd: number | null
    risk_pct: number | null
    position_pct: number | null
    equity_usd: number | null
    risk_per_trade_pct: number
    currency: string | null
    fx_to_usd: number | null
  } | null
  earnings: {
    date: string | null
    days: number | null
    trading_days: number | null
    blackout: boolean
  } | null
  ai: { status: string; provider: string | null; called: boolean }
  score: number | null
  trail: SignalTrail
  caveats: CheckText[]
  checked_at: string
  cached: boolean
}

export interface CheckJobError {
  code: string
  message: string
  status: number
}

export interface CheckJob {
  job_id: string
  input: string
  symbol: string | null
  status: 'running' | 'done' | 'failed'
  phase: CheckPhase | string
  pct: number
  started_at: string
  result?: CheckResult | null
  cached?: boolean
  error?: CheckJobError | null
  remaining_today?: number
}
