export interface Signal {
  id: string
  symbol: string
  name: string | null
  asset_type: 'EQUITY' | 'CRYPTO' | null
  exchange: 'TSX' | 'NYSE' | 'NASDAQ' | 'CRYPTO' | null
  action: 'BUY' | 'HOLD' | 'SELL' | 'AVOID'
  status: 'CONFIRMED' | 'WEAKENING' | 'CANCELLED' | 'UPGRADED'
  score: number
  confidence: number
  is_gem: boolean
  gem_reason: string | null
  bucket: 'SAFE_INCOME' | 'HIGH_RISK' | null
  price_at_signal: number | null
  current_price: number | null
  change_pct: number | null
  target_price: number | null
  stop_loss: number | null
  risk_reward: number | null
  catalyst: string | null
  sentiment_score: number | null
  reasoning: string | null
  entry_window: string | null
  technical_data: Record<string, unknown> | null
  fundamental_data: Record<string, unknown> | null
  macro_data: Record<string, unknown> | null
  grok_data: Record<string, unknown> | null
  account_recommendation: 'TFSA' | 'RRSP' | 'TAXABLE' | null
  superficial_loss_warning: boolean
  market_regime: 'TRENDING' | 'VOLATILE' | 'CRISIS' | null
  catalyst_type: string | null
  scan_id: string | null
  created_at: string
  updated_at: string
}

export interface SignalsResponse {
  signals: Signal[]
  count: number
}

export interface SignalFilters {
  bucket?: 'SAFE_INCOME' | 'HIGH_RISK'
  action?: 'BUY' | 'HOLD' | 'SELL' | 'AVOID'
  status?: 'CONFIRMED' | 'WEAKENING' | 'CANCELLED' | 'UPGRADED'
  period?: 'today' | 'week' | 'month'
  min_score?: number
  limit?: number
}

export interface DailyStats {
  gems_today: number
  gems_yesterday: number
  win_rate_30d: number
  tickers_scanned: number
  next_scan_time: string | null
  ai_cost_today: number
  claude_cost: number
  grok_cost: number
}

export interface ScanTodayRecord {
  id: string | null
  scan_type: 'PRE_MARKET' | 'MORNING' | 'PRE_CLOSE' | 'AFTER_CLOSE'
  label: string
  scheduled_time: string
  status: 'PENDING' | 'RUNNING' | 'COMPLETE' | 'FAILED' | 'CLOSED'
  tickers_scanned: number
  signals_found: number
  gems_found: number
  completed_at: string | null
  is_market_day: boolean
}
