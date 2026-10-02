// Portfolio tracker insights (migration 014) — shapes from back-end/app/api/v1/
// {portfolio_home,dividend_summary,events,allocation}.py docstrings.

/** ?account_id= / ?person_id= (none = whole portfolio). */
export interface Scope {
  account_id?: string
  person_id?: string
}

interface Freshness {
  as_of: string | null
  delayed_minutes: number
}

// ── /portfolio/summary ──

export interface PortfolioSummary extends Freshness {
  currency: string
  market_value: number | null
  cash: number | null
  total: number | null
  day_change: { abs: number | null; pct: number | null }
  total_gain: {
    abs: number | null
    pct: number | null
    unrealized: number | null
    realized: number | null
    dividends: number | null
    dividends_included: boolean
  }
  cost_basis: number | null
  holdings_count: number
  estimated: boolean
  estimated_flags?: {
    prices_from_last_close?: string[]
    unpriced?: string[]
    missing_cost?: string[]
    missing_shares?: string[]
    unconverted?: unknown[]
  }
  usdcad: number | null
  /** US market phase (ET): pre-market 4:00-9:30, after-hours 16:00-20:00 */
  market_phase?: MarketPhase
  /** Premium: change from pre/after-hours trades vs the regular price (null when none) */
  extended?: ExtendedChange | null
  /** Free: held US stocks are trading pre/after hours (show the Premium hint) */
  extended_locked?: boolean
}

export type MarketPhase = 'pre' | 'regular' | 'post' | 'closed'

export interface ExtendedChange {
  session: 'pre' | 'post'
  abs: number | null
  pct: number | null
  as_of: string
  symbols: number
}

/** One symbol's pre-market / after-hours price (stock page, Following). */
export interface ExtendedQuote {
  session: 'pre' | 'post'
  price: number | null
  /** PERCENT vs the regular-session price */
  change_pct: number | null
  as_of: string
}

// ── /portfolio/history ──

export type HistoryRange = '1D' | '1W' | '1M' | '3M' | 'YTD' | '1Y' | '5Y' | 'ALL'

export interface SeriesPoint {
  t: string
  value: number
}

export interface PortfolioHistory extends Freshness {
  range: HistoryRange
  interval: string
  currency: string
  start: string
  end: string
  series: SeriesPoint[]
  range_return_pct: number | null
  estimated: boolean
  estimated_reason: 'no_snapshots' | 'partial_snapshots' | 'no_intraday' | 'no_history' | null
  sources?: { snapshots: number; estimated: number; history_truncated: boolean }
  compare: null | {
    symbol: string
    name: string
    series: SeriesPoint[]
    range_return_pct: number | null
    available: boolean
  }
  /** 1D: the regular session's bounds (Premium 1D includes pre/after-hours bars) */
  session?: { open: string; close: string } | null
}

// ── /portfolio/performance ──

export interface Driver {
  symbol: string
  weight_pct: number | null
  return_pct: number | null
  contribution_pts: number | null
  vs_benchmark_pts?: number | null
}

export interface DriverSet {
  positive: Driver[]
  negative: Driver[]
}

export interface PortfolioPerformance extends Freshness {
  range: HistoryRange
  start: string
  end: string
  currency: string
  method: 'transactions' | 'estimate'
  flows_basis: 'deposits' | 'trades' | null
  return_pct: number | null
  gain: number | null
  start_value: number | null
  end_value: number | null
  net_flows: number | null
  dividends_received: number | null
  drivers: DriverSet
  compare: null | {
    symbol: string
    name: string
    return_pct: number | null
    difference_pts: number | null
    drivers: DriverSet
  }
  estimated: boolean
  estimated_reason: string | null
}

// ── /dividends/summary ──

export type SafetyGrade = 'growing' | 'steady' | 'variable' | 'watch' | 'cut'

export interface DividendSummaryMonth {
  month: string
  total: number
  steady: number
  variable: number
  after_tax: number | null
  days: { date: string; amount: number }[]
}

export interface DividendPayer {
  symbol: string
  annual_amount: number | null
  period_amount: number | null
  share_pct: number | null
  yield_pct: number | null
  frequency: string | null
  safety: SafetyGrade | null
  detail: string
  growth_5y_pct: number | null
  growth_1y_pct: number | null
  months: boolean[]
  next_ex_date: string | null
  next_pay_date: string | null
}

export interface UpcomingPayment {
  symbol: string
  account_id: string | null
  account_name: string | null
  ex_date: string | null
  pay_date: string | null
  pay_date_estimated: boolean
  per_share: number | null
  currency: string | null
  shares: number | null
  cash: number | null
  cash_native: number | null
  after_tax: number | null
  withholding_code: string | null
  estimated: boolean
  ex_passed: boolean
}

export type IncomeChangeKind =
  | 'raise' | 'cut' | 'new_position' | 'removed_position' | 'more_shares' | 'fewer_shares'

export interface IncomeChange {
  days: number
  from_date: string | null
  to_date: string | null
  full_period: boolean
  available_from: string | null
  before_total: number | null
  now_total: number | null
  change: number | null
  components: null | { fx: number; raises: number; cuts: number; new_shares: number; removed_shares: number }
  usdcad_before: number | null
  usdcad_now: number | null
  items: { symbol: string; kind: IncomeChangeKind; amount: number }[]
  reason: null | 'no_history_yet' | 'partial_history' | 'migration_required' | 'whole_portfolio_only'
}

export interface DividendTaxBlock {
  view: 'after'
  country: string
  gross_total: number
  after_tax_total: number
  lost: number
  recoverable: number
  inside_fund: number
  cash_received: number
  by_account_type: {
    account_type: string
    gross: number
    lost: number
    recoverable: number
    inside_fund: number
    after_tax: number
  }[]
  untyped_accounts: { account_id: string; name: string; gross: number }[]
  notes: string[]
}

export interface DividendSummary extends Freshness {
  period: string
  kind: 'expected' | 'received'
  currency: string
  today: string
  usdcad: number | null
  total: number
  steady_total: number
  variable_total: number
  after_tax_total: number | null
  months: DividendSummaryMonth[]
  forward_income: number
  yield_pct: number | null
  yield_on_cost_pct: number | null
  market_value: number | null
  growth: {
    growth_5y_pct: number | null
    growth_1y_pct: number | null
    coverage_5y_pct: number | null
    coverage_1y_pct: number | null
  }
  payers: DividendPayer[]
  non_payers: string[]
  upcoming: UpcomingPayment[]
  income_change: IncomeChange | null
  tax: DividendTaxBlock | null
  tax_reason: null | 'not_eligible' | 'country_not_supported' | 'view_before' | 'ledger_as_recorded'
  unconverted: string[]
  notes?: string[]
}

// ── /portfolio/income-quality/{symbol} ──

export interface IncomeQuality {
  symbol: string
  name: string | null
  pays_dividend: boolean
  yield_pct: number | null
  frequency: string | null
  income_class: 'steady' | 'option_income' | 'cash_like'
  yield_source:
    | 'dividends_from_earnings' | 'dividends_exceed_earnings' | 'fund_distributions' | 'option_premiums' | 'interest'
  flags?: string[]
  payout_history: {
    payments: { ex_date: string; amount: number; special: boolean; change_pct: number | null }[]
    min_change_pct: number | null
    max_change_pct: number | null
  }
  underlying: string | null
  total_return_5y: null | {
    start: string
    end: string
    years: number
    symbol_pct: number | null
    underlying_pct: number | null
  }
  comparison: null | { difference_pct: number | null; currency_mismatch: boolean }
  as_of: string
}

// ── /events/upcoming ──

export type EventType = 'ex_dividend' | 'dividend_payment' | 'earnings' | 'analyst' | 'check_changed' | 'economy' | 'price_alert'

export interface EventItem {
  type: EventType
  date: string
  symbol: string | null
  name: string | null
  title: string
  detail: string
  cash: number | null
  cash_home: number | null
  currency: string | null
  estimated: boolean
  owned: boolean
  recent: boolean
  // dividends
  amount_per_share?: number | null
  shares?: number | null
  ex_date?: string | null
  pay_date?: string | null
  special?: boolean
  frequency?: string | null
  // earnings
  days?: number | null
  trading_days?: number | null
  avg_abs_move_pct?: number | null
  reports_measured?: number | null
  past_moves?: { date: string; move_pct: number }[]
  typical_move_home?: number | null
  // analyst
  firm?: string | null
  action?: string | null
  from_grade?: string | null
  to_grade?: string | null
  price_target?: number | null
  prior_price_target?: number | null
  // check_changed
  changes?: { key: string; from: string; to: string }[]
  previous_date?: string | null
  // economy
  code?: 'boc_rate' | 'fed_rate' | 'us_cpi' | 'ca_cpi'
  country?: 'CA' | 'US'
  // price_alert (a user's alert that fired in the last 7 days; recent=true)
  alert_id?: string
  direction?: 'above' | 'below'
  target_price?: number | null
  last_price?: number | null
  triggered_at?: string | null
}

export interface UpcomingEvents extends Freshness {
  generated_at: string
  today: string
  window: { start: string; end: string; days: number }
  recent_from: string
  home_currency: string
  usdcad: number | null
  symbols: { held: string[]; watched: string[] }
  count: number
  items: EventItem[]
  sources: Record<string, string>
}

// ── /portfolio/allocation ──

export type AllocClass = 'stocks' | 'broad_etfs' | 'option_income_etfs' | 'cash_like' | 'crypto' | 'other'

export interface AllocationWarning {
  code: 'top3_concentration' | 'single_holding' | 'cash_like_high' | 'option_income_high'
  params: { pct?: number; limit?: number; symbols?: string[]; symbol?: string }
}

export interface AllocationTile {
  symbol: string
  name: string | null
  class: AllocClass
  value_home: number
  weight_pct: number
  day_change_pct: number | null
  total_gain_pct: number | null
}

export interface Allocation extends Freshness {
  home_currency: string
  estimated_prices: string[]
  scope: { account_id: string | null; person_id: string | null }
  total_home: number
  invested_home: number
  cash_home: number
  mix: { class: AllocClass; value_home: number; pct: number }[]
  tiles: AllocationTile[]
  warnings: AllocationWarning[]
  unpriced: string[]
  targets: Partial<Record<AllocClass, number>> | null
}

export interface AllocationTargets {
  targets: Partial<Record<AllocClass, number>> | null
  classes: AllocClass[]
}

export interface AllocationPlan extends Freshness {
  home_currency: string
  targets: Partial<Record<AllocClass, number>>
  amount: number
  allocated: number
  unallocated: number
  items: {
    class: AllocClass
    amount: number
    gap_home: number
    current_pct: number
    target_pct: number
    after_pct: number
    buy: { symbol: string | null; source: 'largest_holding' | 'default' | null; code: 'no_default' | null }
  }[]
}
