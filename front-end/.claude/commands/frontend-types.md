Show all TypeScript types and interfaces for the Signa frontend.

## Signal (`src/types/signal.ts`)

```typescript
interface Signal {
  id: string
  symbol: string
  name: string | null
  asset_type: 'EQUITY' | 'CRYPTO' | null
  exchange: 'TSX' | 'NYSE' | 'NASDAQ' | 'CRYPTO' | null
  action: 'BUY' | 'HOLD' | 'SELL' | 'AVOID'
  status: 'CONFIRMED' | 'WEAKENING' | 'CANCELLED' | 'UPGRADED'
  score: number                              // 0-100
  confidence: number                         // 0-100
  is_gem: boolean                            // High-conviction signal
  gem_reason: string | null
  bucket: 'SAFE_INCOME' | 'HIGH_RISK' | null
  price_at_signal: number | null
  current_price: number | null
  change_pct: number | null
  target_price: number | null
  stop_loss: number | null
  risk_reward: number | null                 // Ratio like 2.5
  catalyst: string | null                    // What triggered the signal
  sentiment_score: number | null             // From Grok/X analysis
  reasoning: string | null                   // AI-generated explanation (top 15 only)
  entry_window: string | null                // Time window for entry
  technical_data: Record<string, unknown> | null   // RSI, MACD, etc.
  fundamental_data: Record<string, unknown> | null // PE, EPS, etc.
  macro_data: Record<string, unknown> | null       // Market regime data
  grok_data: Record<string, unknown> | null        // X/Twitter sentiment
  account_recommendation: 'TFSA' | 'RRSP' | 'TAXABLE' | null  // Canadian tax optimization
  superficial_loss_warning: boolean          // CRA 30-day rule flag
  market_regime: 'TRENDING' | 'VOLATILE' | 'CRISIS' | null
  catalyst_type: string | null
  signal_style: 'MOMENTUM' | 'CONTRARIAN' | 'NEUTRAL' | null
  contrarian_score: number | null
  scan_id: string | null
  created_at: string
  updated_at: string
}

interface SignalFilters {
  bucket?: 'SAFE_INCOME' | 'HIGH_RISK'
  action?: 'BUY' | 'HOLD' | 'SELL' | 'AVOID'
  status?: 'CONFIRMED' | 'WEAKENING' | 'CANCELLED' | 'UPGRADED'
  period?: 'today' | 'week' | 'month'
  min_score?: number
  limit?: number
}

interface DailyStats {
  gems_today: number
  gems_yesterday: number
  win_rate_30d: number           // 0-1 decimal, multiply by 100 for display
  tickers_scanned: number
  next_scan_time: string | null  // ISO datetime
  ai_cost_today: number
  claude_cost: number
  grok_cost: number
}

interface ScanTodayRecord {
  id: string | null
  scan_type: 'PRE_MARKET' | 'MORNING' | 'PRE_CLOSE' | 'AFTER_CLOSE'
  label: string
  scheduled_time: string
  status: 'PENDING' | 'RUNNING' | 'COMPLETE' | 'FAILED' | 'CLOSED'
  tickers_scanned: number
  signals_found: number
  gems_found: number
  started_at: string | null
  completed_at: string | null
  duration_seconds: number | null
  is_market_day: boolean
}
```

## Auth (`src/types/auth.ts`)

```typescript
interface LoginRequest { username: string; password: string }
interface LoginResponse { message: string; session_token: string }
interface OtpVerifyRequest { session_token: string; otp_code: string }
interface AuthResponse { access_token: string; token_type: string; expires_in: number }
```

## Watchlist (`src/types/watchlist.ts`)

```typescript
interface WatchlistItem { id: string; symbol: string; added_at: string; notes: string | null }
interface WatchlistAddRequest { notes?: string }
```

## Portfolio (`src/types/portfolio.ts`)

```typescript
interface PortfolioItem {
  id: string; symbol: string; bucket: 'SAFE_INCOME' | 'HIGH_RISK' | null
  account_type: 'TFSA' | 'RRSP' | 'TAXABLE' | null
  shares: number | null; avg_cost: number | null; currency: 'CAD' | 'USD'
  created_at: string; updated_at: string
}

interface Position {
  id: string; symbol: string; entry_price: number; entry_date: string; shares: number
  account_type: 'TFSA' | 'RRSP' | 'TAXABLE' | null
  bucket: 'SAFE_INCOME' | 'HIGH_RISK' | null; currency: 'CAD' | 'USD'
  target_price: number | null; stop_loss: number | null; notes: string | null
  status: 'OPEN' | 'CLOSED' | 'STOPPED_OUT'
  exit_price: number | null; exit_date: string | null
  exit_reason: 'USER_CLOSE' | 'TARGET_HIT' | 'STOP_HIT' | 'SIGNAL_WEAKENED' | null
  pnl_amount: number | null; pnl_percent: number | null
  last_signal_score: number | null; last_signal_status: string | null
  created_at: string; updated_at: string
}
```

## Chart (`src/types/chart.ts`)

```typescript
interface PricePoint { date: string; price: number }
type TimeRange = '1D' | '1W' | '1M' | '3M'
```

## Scan (`src/types/scan.ts`)

```typescript
interface ScanRecord {
  id: string; scan_type: 'PRE_MARKET' | 'MORNING' | 'PRE_CLOSE' | 'AFTER_CLOSE'
  started_at: string; completed_at: string | null
  tickers_scanned: number; signals_found: number; gems_found: number
  status: 'RUNNING' | 'COMPLETE' | 'FAILED'; error_message: string | null
  created_at: string
}
```

## API Response Types (in `src/lib/api.ts`)

```typescript
interface TickerDetail {
  ticker: string; name: string; company_name: string | null
  exchange: string; asset_type: string | null
  sector: string | null; industry: string | null
  market_cap: number | null; pe_ratio: number | null; eps: number | null
  dividend_yield: number | null; beta: number | null
  week_52_high: number | null; week_52_low: number | null; avg_volume: number | null
  current_price: number | null; day_change_pct: number | null
  fundamentals: Record<string, unknown> | null
}

interface ScanProgress {
  scan_id: string; status: string; phase: string
  current_ticker: string | null
  tickers_done: number; tickers_total: number
  signals_found: number; gems_found: number
  error_message: string | null
}
```

## Theme Type (in `src/lib/themes.ts`)

```typescript
type ThemeId = 'applestocks' | 'robinhood' | 'wealthsimple' | 'bloomberg' | 'webull' | 'etrade'

interface Theme {
  id: ThemeId; name: string; description: string; isDark: boolean
  colors: {
    bg: string; surface: string; surfaceAlt: string
    text: string; textSub: string; textHint: string
    primary: string; accent: string
    up: string; down: string; warning: string
    border: string; stripeRisk: string; stripeSafe: string
  }
}
```

## Store Types (Zustand)

```typescript
// authStore
interface AuthStore {
  token: string | null; isAuthenticated: boolean
  setToken(token: string): void; logout(): void; initialize(): void
}

// brainStore
interface BrainStore {
  brainToken: string | null; brainTokenExpiry: Date | null; isUnlocked: boolean
  setBrainToken(token: string, expiresIn: number): void
  lock(): void; getRemainingSeconds(): number
  getHeaders(): Record<string, string>  // { 'X-Brain-Token': token } or {}
}

// i18nStore
interface I18nStore {
  locale: 'en' | 'pt'; t: Translations
  setLocale(locale: 'en' | 'pt'): void; initialize(): void
}

// themeStore
interface ThemeStore {
  themeId: ThemeId; theme: Theme
  setTheme(id: ThemeId): void; initialize(): void
}
```
