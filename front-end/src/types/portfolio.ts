export interface PortfolioItem {
  id: string
  symbol: string
  bucket: 'SAFE_INCOME' | 'HIGH_RISK' | null
  account_type: 'TFSA' | 'RRSP' | 'TAXABLE' | null
  shares: number | null
  avg_cost: number | null
  currency: 'CAD' | 'USD'
  created_at: string
  updated_at: string
}

export interface PortfolioResponse {
  items: PortfolioItem[]
  count: number
}

export interface PortfolioAddRequest {
  symbol: string
  bucket?: 'SAFE_INCOME' | 'HIGH_RISK' | null
  account_type?: 'TFSA' | 'RRSP' | 'TAXABLE' | null
  shares?: number
  avg_cost?: number
  currency?: 'CAD' | 'USD'
}

export interface PortfolioUpdateRequest {
  bucket?: 'SAFE_INCOME' | 'HIGH_RISK' | null
  account_type?: 'TFSA' | 'RRSP' | 'TAXABLE' | null
  shares?: number
  avg_cost?: number
  currency?: 'CAD' | 'USD'
}

export interface Position {
  id: string
  symbol: string
  entry_price: number
  entry_date: string
  shares: number
  account_type: 'TFSA' | 'RRSP' | 'TAXABLE' | null
  bucket: 'SAFE_INCOME' | 'HIGH_RISK' | null
  currency: 'CAD' | 'USD'
  target_price: number | null
  stop_loss: number | null
  notes: string | null
  status: 'OPEN' | 'CLOSED' | 'STOPPED_OUT'
  exit_price: number | null
  exit_date: string | null
  exit_reason: 'USER_CLOSE' | 'TARGET_HIT' | 'STOP_HIT' | 'SIGNAL_WEAKENED' | null
  pnl_amount: number | null
  pnl_percent: number | null
  last_signal_score: number | null
  last_signal_status: string | null
  created_at: string
  updated_at: string
}

export interface PositionsResponse {
  positions: Position[]
  count: number
}

export interface PositionOpenRequest {
  symbol: string
  entry_price: number
  shares: number
  account_type?: 'TFSA' | 'RRSP' | 'TAXABLE' | null
  bucket?: 'SAFE_INCOME' | 'HIGH_RISK' | null
  currency?: 'CAD' | 'USD'
  target_price?: number
  stop_loss?: number
  notes?: string
}

export interface PositionUpdateRequest {
  target_price?: number
  stop_loss?: number
  notes?: string
}

export interface PositionCloseRequest {
  exit_price: number
}
