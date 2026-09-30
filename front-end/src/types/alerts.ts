// Price alerts — /api/v1/alerts (back-end/app/api/v1/alerts.py, migration 015)

export type AlertDirection = 'above' | 'below'

export interface PriceAlert {
  id: string
  symbol: string
  direction: AlertDirection
  /** in `currency` */
  target_price: number
  currency: string
  note: string | null
  active: boolean
  /** set when it fired (then active=false) */
  triggered_at: string | null
  last_price: number | null
  created_at: string
  /** latest shared quote in the alert currency (delayed ~15 min) */
  current_price: number | null
  /** (target / current - 1) x 100 — PERCENT; null when inactive or unpriced */
  distance_pct: number | null
  as_of: string | null
}

export interface AlertsResponse {
  items: PriceAlert[]
  count: number
  symbol: string | null
  /** active alerts over all symbols */
  active: number
  /** null = unlimited */
  limit: number | null
  remaining: number | null
}

export interface AlertInput {
  symbol: string
  direction: AlertDirection
  target_price: number
  currency?: string
  note?: string | null
}

export interface AlertPatch {
  direction?: AlertDirection
  target_price?: number
  currency?: string
  note?: string | null
  active?: boolean
}
