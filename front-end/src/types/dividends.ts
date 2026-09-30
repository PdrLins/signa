// GET /dividends/calendar — see back-end app/services/dividend_calendar.py

export interface DividendMoney {
  /** currency code -> amount */
  by_currency: Record<string, number>
  total_cad: number | null
  /** a currency couldn't be converted to CAD (total_cad is partial) */
  fx_missing: boolean
}

export interface DividendEvent {
  symbol: string
  name: string | null
  /** pay_date, falling back to ex_date (ISO date) */
  date: string
  ex_date: string
  pay_date: string | null
  pay_date_estimated: boolean
  amount_per_share: number | null
  currency: string
  /** ex-date / amount projected from history, not announced */
  estimated: boolean
  special: boolean
  /** ex-date already passed, payment still to come */
  ex_passed: boolean
  frequency: string | null
  shares: number | null
  expected_cash: number | null
  expected_cash_cad: number | null
  account: string | null
  owned: boolean
}

export interface DividendMonth {
  /** "YYYY-MM" */
  month: string
  total: DividendMoney
  events: DividendEvent[]
}

export type DividendPositionStatus = 'payer' | 'non_payer' | 'unknown'

export interface DividendPosition {
  symbol: string
  name: string | null
  owned: boolean
  account: string | null
  shares: number | null
  currency: string
  price: number | null
  status: DividendPositionStatus
  reason: string | null
  frequency: string | null
  annual_rate: number | null
  yield_pct: number | null
  annual_income: number | null
  annual_income_cad: number | null
  next_ex_date: string | null
  next_pay_date: string | null
}

export interface DividendCalendarSummary {
  income_window: DividendMoney
  income_next_12m: DividendMoney
  annual_income: DividendMoney
  next_payment: DividendEvent | null
  next_ex_date: DividendEvent | null
  payers: number
  non_payers: number
  unknown: number
  holdings: number
  missing_shares: number
  forward_yield_pct: number | null
  market_value_cad: number | null
}

export interface DividendSymbolRef {
  symbol: string
  name: string | null
}

export interface DividendCalendarResponse {
  as_of: string
  window: { start: string; end: string; months: number }
  usdcad: number | null
  include_watchlist: boolean
  summary: DividendCalendarSummary
  months: DividendMonth[]
  events: DividendEvent[]
  positions: DividendPosition[]
  non_payers: (DividendSymbolRef & { reason: 'crypto' | 'no_dividend' | 'suspended' | string; owned: boolean })[]
  unknown: (DividendSymbolRef & { owned: boolean })[]
  missing_shares: DividendSymbolRef[]
}
