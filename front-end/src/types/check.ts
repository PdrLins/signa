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

// ── Dividends (back-end/app/services/dividends.py) ──────────────────

export type DividendFrequency = 'monthly' | 'quarterly' | 'semiannual' | 'annual' | 'irregular'

export interface DividendScheduleRow {
  ex_date: string
  pay_date: string | null
  /** per share, in the listing currency (projected) */
  amount: number | null
  /** the ex-date is projected, not announced */
  estimated: boolean
  pay_estimated: boolean
}

export interface DividendProfile {
  symbol: string
  pays_dividend: boolean
  suspended: boolean
  /** why pays_dividend is false: no_dividend | crypto | suspended | unavailable */
  reason: string | null
  currency: string | null
  /** per share per year */
  annual_rate: number | null
  /** FRACTION (0.03 == 3%) */
  yield: number | null
  /** FRACTION of earnings */
  payout_ratio: number | null
  /** FRACTION */
  five_year_avg_yield: number | null
  frequency: DividendFrequency | null
  interval_days: number | null
  next_ex_date: string | null
  next_pay_date: string | null
  next_amount: number | null
  next_estimated: boolean | null
  next_pay_estimated: boolean | null
  upcoming: DividendScheduleRow[]
  /** newest first */
  last_payments: { ex_date: string; amount: number; special: boolean }[]
  /** FRACTION per year */
  growth_5y_cagr: number | null
  years_without_cut: number | null
  last_cut_date: string | null
  recent_cut: boolean
  is_fund: boolean
}

/** One deterministic dividend rule outcome; the UI renders
 *  t.check.dividend.rules[code] with `params`, `text` is the English fallback. */
export interface DividendRule {
  code: string
  effect: 'positive' | 'negative' | 'caution' | 'info'
  text: string
  params: Record<string, string | number | boolean | null>
}

/** "short" = is the next days/weeks a good swing entry; "long" = is this a
 *  sound long-term holding (back-end/app/services/long_term_check.py). */
export type CheckMode = 'short' | 'long'

export type CheckPhase =
  | 'resolving' | 'market_data' | 'filter' | 'sentiment' | 'synthesis' | 'decision' | 'risk' | 'done'

export type LongCheckPhase =
  | 'resolving' | 'history' | 'benchmark' | 'fundamentals' | 'sentiment' | 'assessment' | 'done'

export interface CheckResult {
  mode?: 'short'
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
    /** set when an ex-dividend date falls inside the trade window */
    dividend?: {
      ex_date: string
      trading_days: number
      amount: number | null
      /** percent of the price */
      pct: number | null
      estimated: boolean
      pay_date: string | null
      rr_with_dividend: number | null
    } | null
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
  /** absent on results cached before dividends were added */
  dividend?: DividendProfile | null
  dividend_rules?: DividendRule[]
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
  mode?: CheckMode
  status: 'running' | 'done' | 'failed'
  phase: CheckPhase | string
  pct: number
  started_at: string
  result?: AnyCheckResult | null
  cached?: boolean
  error?: CheckJobError | null
  remaining_today?: number
}

// ── Long-term mode ──────────────────────────────────────────────────

export type LongVerdict = 'SOLID' | 'REASONABLE_WITH_CAVEATS' | 'NOT_A_GOOD_FIT'
export type Rating = 'good' | 'fair' | 'poor' | 'n/a'

export interface ScorecardItem {
  key: 'cost' | 'diversification' | 'track_record' | 'valuation' | 'risk' | 'quality' | 'dividend' | string
  /** stable reason-template id (t.check.long.reasons[key][code]) */
  code: string
  rating: Rating
  /** English fallback */
  reason: string
  params: Record<string, string | number | null>
}

export interface ReturnRow {
  period: string
  years: number
  /** all percentages */
  asset_total: number
  asset_cagr: number
  benchmark_total: number | null
  benchmark_cagr: number | null
  excess_cagr: number | null
}

export interface LongDrawdowns {
  max: {
    depth_pct: number
    peak_date: string | null
    trough_date: string | null
    recovery_date: string | null
    recovered: boolean
    recovery_days: number | null
    underwater_days: number | null
  } | null
  current: { pct: number; ath: number; ath_date: string } | null
  worst_year: { year: number; return: number } | null
  calendar_years: { year: number; return: number }[]
  volatility: number | null
  history_years: number
  since_inception: { total: number; cagr: number | null; years: number; start: string } | null
}

export interface FundInfo {
  /** percent (0.2 == 0.20%/yr) */
  expense_ratio: number | null
  expense_ratio_source: string | null
  aum: number | null
  /** percent */
  yield: number | null
  family: string | null
  category: string | null
  legal_type: string | null
  inception_date: string | null
  /** weight in percent */
  top_holdings: { symbol: string; name: string | null; weight: number | null }[]
  holdings_listed: number
  top10_weight: number | null
  fund_of_funds: boolean
  /** percent by Yahoo sector key (e.g. financial_services) */
  sector_weights: Record<string, number>
  /** percent by Yahoo key (stockPosition, bondPosition, cashPosition, ...) */
  asset_classes: Record<string, number>
  pe: number | null
  pb: number | null
  turnover: number | null
}

export interface StockFundamentals {
  market_cap: number | null
  sector: string | null
  industry: string | null
  /** fcf_yield in percent */
  valuation: { trailing_pe: number | null; forward_pe: number | null; peg: number | null; price_to_book: number | null; ev_to_ebitda: number | null; fcf_yield: number | null }
  /** roe / margins in percent; debt_to_equity in percent (150 == 1.5x) */
  quality: { roe: number | null; profit_margin: number | null; operating_margin: number | null; debt_to_equity: number | null; current_ratio: number | null }
  growth: {
    revenue_growth: number | null
    earnings_growth: number | null
    revenue_cagr: number | null
    net_income_cagr: number | null
    trend: { year: number; revenue: number | null; net_income: number | null }[]
  }
  dividend: { yield: number | null; payout_ratio: number | null; five_year_avg_yield: number | null }
  estimates: { revision_momentum: number | null; up_30d: number | null; down_30d: number | null; fy1_change_90d: number | null }
}

export interface LongAssessment {
  verdict: LongVerdict
  summary: string
  strengths: string[]
  concerns: string[]
  what_to_watch: string[]
  dca_note: string | null
  confidence: number
}

export interface LongCheckResult {
  mode: 'long'
  input: string
  symbol: string
  exchange: string | null
  name: string | null
  asset_type: 'STOCK' | 'ETF' | 'CRYPTO' | 'OTHER' | string
  currency: string | null
  price: number | null
  verdict: LongVerdict
  verdict_source: 'ai' | 'scorecard'
  scorecard_verdict: LongVerdict
  ai_assessment: LongAssessment | null
  ai: { called: boolean; provider: string | null; sentiment_called: boolean; status: 'ok' | 'failed' | 'disabled' | string }
  scorecard: ScorecardItem[]
  returns: ReturnRow[]
  benchmark: string | null
  drawdowns: LongDrawdowns
  fund: FundInfo | null
  fundamentals: StockFundamentals | null
  red_flags: { text: string; url: string | null; severity: string | null; category: string | null }[]
  /** absent on results cached before dividends were added */
  dividend?: DividendProfile | null
  dividend_rules?: DividendRule[]
  /** deterministic caps applied over the AI / scorecard verdict */
  verdict_adjustments?: { code: string; from: LongVerdict; to: LongVerdict }[]
  notes: CheckText[]
  data_as_of: string
  caveats: CheckText[]
  checked_at: string
  cached: boolean
}

export type AnyCheckResult = CheckResult | LongCheckResult

export function isLongResult(r: AnyCheckResult | null | undefined): r is LongCheckResult {
  return !!r && (r as LongCheckResult).mode === 'long'
}

// ── Compare 2–3 symbols (/check/compare) ────────────────────────────

export type CompareItemStatus = 'queued' | 'running' | 'done' | 'failed'

export interface CompareItem {
  input: string
  symbol: string
  status: CompareItemStatus
  phase: CheckPhase | LongCheckPhase | 'queued' | string
  pct: number
  /** null until done */
  cached: boolean | null
  error: CheckJobError | null
}

export type CompareFormat =
  | 'verdict' | 'bool' | 'num' | 'signal' | 'int' | 'prob' | 'ratio' | 'days' | 'corr' | 'pct' | 'rating' | 'date'

export interface CompareMetric {
  key: string
  group: string
  format: CompareFormat | string
  /** null = informational (never marked best) */
  better: 'higher' | 'lower' | null
  values: Record<string, string | number | boolean | null>
  /** symbols holding the best value (ties allowed); null = not comparable */
  best: string[] | null
  detail?: Record<string, unknown>
}

export interface CompareIdentity {
  symbol: string
  name: string | null
  exchange: string | null
  currency: string | null
  price: number | null
  asset_type: string | null
  verdict: CheckVerdict | LongVerdict | string
  cached: boolean
  checked_at: string | null
}

export interface Comparison {
  mode: CheckMode
  symbols: string[]
  identity: Record<string, CompareIdentity>
  metrics: CompareMetric[]
  best_counts: Record<string, number>
}

export interface CompareSummary {
  source: 'ai' | 'deterministic'
  /** best -> worst */
  ranking: string[]
  /** AI text (English); null for the deterministic ranking */
  summary: string | null
  per_symbol: Record<string, string>
  caveats: string[]
  note: { code: string; text: string } | null
  provider: string | null
}

export interface CompareJob {
  compare_id: string
  mode: CheckMode
  status: 'running' | 'done'
  phase: 'checking' | 'summarizing' | 'done' | string
  pct: number
  symbols: string[]
  items: CompareItem[]
  started_at: string
  results?: Record<string, AnyCheckResult>
  comparison?: Comparison | null
  summary?: CompareSummary | null
  remaining_today?: number
}
