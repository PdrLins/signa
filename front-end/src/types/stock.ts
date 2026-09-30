// Free stock page — GET /api/v1/stocks/{symbol}
// (back-end/app/api/v1/stocks.py, app/services/stock_page.py)
import type { DividendProfile, DividendRule } from '@/types/check'

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
  generated_at: string
  followed: { in_holdings: boolean; in_watchlist: boolean }
}
