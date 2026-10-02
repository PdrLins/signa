export interface WatchlistItem {
  id: string
  symbol: string
  added_at: string
  notes: string | null
}

export interface WatchlistResponse {
  items: WatchlistItem[]
  count: number
}

export interface WatchlistAddRequest {
  notes?: string
}

/** GET /watchlist/overview — the Following tab. */
export interface FollowingRow {
  symbol: string
  name: string | null
  price: number | null
  /** today, % */
  change_pct: number | null
  change_1m_pct: number | null
  currency: string | null
  as_of: string | null
  /** up to 22 daily closes, oldest first (may be empty) */
  spark: number[]
  in_holdings: boolean
  added_at?: string
  /** Premium: pre-market / after-hours price */
  extended?: import('./tracker').ExtendedQuote | null
  extended_locked?: boolean
}

export interface SuggestionItem {
  symbol: string
  name: string
  /** optional: shared quote when available */
  price?: number | null
  /** today, PERCENT */
  change_pct?: number | null
  currency?: string | null
}

export type SuggestionGroupKey = 'popular_ca' | 'popular_us' | 'monthly_income' | 'dividend_growers'

export interface FollowingOverview {
  as_of: string | null
  delayed_minutes: number
  watched: FollowingRow[]
  held: FollowingRow[]
  slots: { used: number; limit: number | null; remaining: number | null } | null
  suggestions: { key: SuggestionGroupKey; items: SuggestionItem[] }[]
}
