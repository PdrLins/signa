// My holdings — the owner's REAL long-term positions (back-end/app/api/v1/holdings.py).

export type HoldingAccount = 'TFSA' | 'RRSP' | 'FHSA' | 'NON_REGISTERED' | 'OTHER'
export type HoldingAssetType = 'STOCK' | 'ETF' | 'CRYPTO' | 'OTHER'
export type LongVerdictCode = 'SOLID' | 'REASONABLE_WITH_CAVEATS' | 'NOT_A_GOOD_FIT'
export type TrendState = 'ok' | 'weak' | 'break' | 'unknown'

export interface HoldingRedFlag {
  text: string
  url: string | null
  severity: string | null
  category: string | null
  key?: string
}

export interface HoldingPosition {
  currency: string
  value: number | null
  value_cad: number | null
  book_value: number | null
  unrealized: number | null
  unrealized_pct: number | null
  weight_pct: number | null
  overweight: boolean
}

export interface HoldingStatus {
  price?: number | null
  prev_close?: number | null
  day_change_pct?: number | null
  change_1m_pct?: number | null
  ytd_pct?: number | null
  sma50?: number | null
  sma200?: number | null
  pct_vs_sma200?: number | null
  trend?: TrendState
  trend_break?: boolean
  death_cross?: boolean
  high_52w?: number | null
  drawdown_pct?: number | null
  as_of?: string
  earnings?: { date: string | null; days: number | null; trading_days: number | null } | null
  red_flags?: HoldingRedFlag[]
  sentiment?: { checked_on?: string | null; provider?: string | null; cached?: boolean; skipped?: string; error?: string }
  stale?: boolean
  error?: string
  updated_at?: string
}

export interface HoldingReview {
  verdict: LongVerdictCode | null
  verdict_source: 'ai' | 'scorecard' | null
  summary: string | null
  confidence: number | null
  scorecard: { key: string; rating: 'good' | 'fair' | 'poor' | 'n/a' }[]
  key_concern: string | null
  key_concern_source: string | null
  red_flags: number
  asset_type: string | null
  reviewed_at: string
}

export interface Holding {
  id: string
  symbol: string
  input_symbol: string | null
  name: string | null
  exchange: string | null
  currency: string | null
  asset_type: HoldingAssetType | null
  shares: number | null
  avg_cost: number | null
  /** deprecated (migration 013): legacy tax label, no longer written */
  account: HoldingAccount | null
  /** The user's account holding this lot (null = no account / before 013). */
  account_id: string | null
  account_name: string | null
  person_id: string | null
  notes: string | null
  holding_status: HoldingStatus | null
  status_updated_at: string | null
  last_review: HoldingReview | null
  last_reviewed_at: string | null
  created_at: string
  updated_at: string
  position: HoldingPosition | null
  flags: { covered_call: boolean; leveraged: boolean; cash_like: boolean; us_large_tech_fund: boolean }
}

export interface HoldingsTotals {
  currency: 'CAD'
  value_cad: number | null
  book_value_cad: number | null
  unrealized_cad: number | null
  unrealized_pct: number | null
  count: number
  count_with_shares: number
  usdcad: number | null
  fx_missing: boolean
  max_weight_pct: number
}

export interface ReviewAllInfo {
  last_at: string | null
  next_allowed_at: string | null
  allowed: boolean
  days: number
}

export interface HoldingsResponse {
  items: Holding[]
  count: number
  totals: HoldingsTotals
  monitor_running: boolean
  review_running: boolean
  review_all: ReviewAllInfo
  settings: { max_weight_pct: number; alerts_enabled: boolean; review_max_ids: number }
  filter?: { account_id: string | null; person_id: string | null }
}

export interface Listing {
  symbol: string
  name: string | null
  exchange: string
  currency: string
  asset_type: HoldingAssetType
  price: number
}

export interface ResolvedLine {
  line: number
  raw: string
  input: string
  shares: number | null
  avg_cost: number | null
  account: HoldingAccount | null
  error: string | null
  merged?: number
  status: 'ok' | 'ambiguous' | 'not_found' | 'invalid'
  selected: Listing | null
  alternatives: Listing[]
  note: 'prefer_tsx' | 'prefer_known' | 'cdr' | null
  existing: boolean
}

export interface ResolveResponse {
  lines: ResolvedLine[]
  count: number
  counts: Record<'ok' | 'ambiguous' | 'not_found' | 'invalid', number>
}

export interface HoldingUpsertItem {
  symbol: string
  input_symbol?: string | null
  name?: string | null
  exchange?: string | null
  currency?: string | null
  asset_type?: HoldingAssetType | null
  shares?: number | null
  avg_cost?: number | null
  /** The user's account (the legacy `account` field is deprecated and not sent). */
  account_id?: string | null
  notes?: string | null
}

export interface HoldingPatch {
  shares?: number | null
  avg_cost?: number | null
  /** Move the holding to another account (null = no account). */
  account_id?: string | null
  notes?: string | null
}

export interface ReviewJob {
  job_id: string
  mode: 'all' | 'selected'
  status: 'running' | 'done' | 'failed'
  total: number
  done: number
  current: string | null
  pct: number
  results: { id: string; symbol: string; verdict?: LongVerdictCode | null; cached?: boolean; error?: string }[]
  started_at: string
}

export interface AllocateFactor {
  code: string
  points: number
  params: Record<string, number | string | null>
}

export interface AllocateIdea {
  id: string | null
  symbol: string
  name: string | null
  source: 'holding' | 'watchlist'
  score: number
  tier: 'consider' | 'neutral' | 'caution'
  factors: AllocateFactor[]
  reason: string
  verdict: LongVerdictCode | null
  weight_pct: number | null
  rank: number
}

export interface AllocateNote {
  code: string
  symbols: string[]
  text: string
}

export interface AllocateResponse {
  ideas: AllocateIdea[]
  notes: AllocateNote[]
  caveat: string
  max_weight_pct: number
  generated_at: string
  count_with_shares: number
}
