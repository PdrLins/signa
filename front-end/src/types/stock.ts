// Free stock page — GET /api/v1/stocks/{symbol}
// (back-end/app/api/v1/stocks.py, app/services/stock_page.py)
import type { DividendProfile, DividendRule } from '@/types/check'
import type { SlotSummary } from '@/types/access'

export type StockAssetType = 'stock' | 'etf' | 'crypto'

export type StockCheckKey = 'uptrend' | 'not_overheated' | 'liquidity' | 'earnings_soon' | 'dividend_health'

export type StockCheckStatus = 'pass' | 'warn' | 'fail' | 'na'

export interface StockQuote {
  /** listing currency */
  price: number | null
  /** 1-day change, PERCENT */
  change_pct: number | null
  high_52w: number | null
  low_52w: number | null
  market_cap: number | null
  /** ISO datetime of the price */
  as_of: string | null
}

/** One rule-based check. The UI renders t.stock.checks[key][detail_code]
 *  with `params`; checks describe the stock, they are not advice. */
export interface StockCheck {
  key: StockCheckKey
  status: StockCheckStatus
  value: number | string | null
  detail_code: string
  params: Record<string, string | number | null>
}

export interface StockEvents {
  earnings: { date: string | null; days: number | null; trading_days: number | null } | null
  ex_dividend: { date: string; estimated: boolean; amount: number | null } | null
  dividend_payment: { date: string; estimated: boolean } | null
}

/** Key statistics (shared, cached with the page); each nullable. */
export interface StockStatistics {
  day_low: number | null
  day_high: number | null
  low_52w: number | null
  high_52w: number | null
  market_cap: number | null
  pe_ratio: number | null
  forward_pe: number | null
  /** FRACTION (0.035 = 3.5%) */
  dividend_yield: number | null
  /** ~3-month average daily volume (shares) */
  avg_volume: number | null
  volume: number | null
  beta: number | null
}

export interface StockPL {
  abs: number | null
  /** PERCENT */
  pct: number | null
  abs_home: number | null
}

/** The user's position in this stock across accounts (never cached). */
export interface StockPosition {
  shares: number
  /** share-weighted over lots with a cost */
  avg_cost: number | null
  /** listing currency */
  currency: string
  price: number | null
  home_currency: string
  market_value: number | null
  market_value_home: number | null
  /** PERCENT of the portfolio's priced market value (home currency, excl. cash) */
  weight_pct: number | null
  today_pl: StockPL
  open_pl: StockPL
  /** from the ledger; null without transactions */
  dividends_received: number | null
  realized_pl: number | null
  /** open + dividends + realized */
  total_gain: StockPL
  has_transactions: boolean
  price_source: 'quote' | 'last_close' | null
  as_of: string | null
  per_account: {
    account_id: string | null
    account_name: string | null
    shares: number
    avg_cost: number | null
    value: number | null
    value_home: number | null
  }[]
}

export interface StockPage {
  /** resolved symbol (XEQT -> XEQT.TO) */
  symbol: string
  name: string | null
  exchange: string
  exchange_name: string | null
  currency: string
  asset_type: StockAssetType
  sector: string | null
  industry: string | null
  quote: StockQuote
  dividend: {
    profile: DividendProfile
    rating: 'good' | 'fair' | 'poor' | 'n/a'
    rating_code: string
    rules: DividendRule[]
  }
  events: StockEvents
  checks: StockCheck[]
  statistics: StockStatistics
  generated_at: string
  // ---- this user (never cached) ----
  followed: { in_holdings: boolean; in_watchlist: boolean }
  /** null = not held */
  position: StockPosition | null
  /** limit/remaining null = unlimited; null when unavailable */
  slots: SlotSummary | null
}
