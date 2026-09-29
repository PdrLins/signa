import type { Theme } from '@/lib/themes'
import { DEFAULT_TIMEZONE } from '@/lib/utils'
import { intlLocale } from '@/store/i18nStore'

// ── Track record types ──

export interface TrackRecordRange {
  score_range: string
  trades: number
  win_rate: number
  avg_return_pct: number
}

export interface TrackRecordData {
  ranges: TrackRecordRange[]
  total_trades: number
  overall_win_rate: number
  by_source: {
    brain: { ranges: TrackRecordRange[]; total_trades: number; win_rate: number }
    watchlist: { ranges: TrackRecordRange[]; total_trades: number; win_rate: number }
  }
}

// ── Types ──

export interface TrackStats {
  open_count: number
  closed_count: number
  wins: number
  losses: number
  win_rate: number
  avg_return_pct: number
  total_return_pct: number
  // Wallet vs legacy split. pnl_amount semantics differ: wallet trades
  // store TOTAL dollars, legacy store per-share — summing across them
  // would mix units, so the two totals are reported separately.
  wallet_closed_count?: number
  legacy_closed_count?: number
  total_pnl_amount_wallet?: number
  total_pnl_amount_legacy?: number
  avg_unrealized_pnl_pct?: number
  best_trade: { symbol: string; pnl_pct: number; pnl_amount?: number } | null
  worst_trade: { symbol: string; pnl_pct: number; pnl_amount?: number } | null
}

export interface VirtualTrade {
  symbol: string
  entry_price: number
  entry_score: number
  bucket: string
  source: string
  signal_style?: string
  target_price?: number
  stop_loss?: number
  days_held?: number
  current_price?: number
  unrealized_pnl_pct?: number
  unrealized_pnl_amount?: number
  current_score?: number
  reasoning?: string
  risk_reward?: number
  contrarian_score?: number
  market_regime?: string
  thesis_status?: string  // valid | weakening | invalid | null (legacy)
  tier_reason?: string    // validated | validated_below_sma50 | low_confidence_high_score | tech_only_confirmed_*
  trade_horizon?: 'SHORT' | 'LONG'
  direction?: 'LONG' | 'SHORT'
  consecutive_avoid_count?: number
  // Wallet fields (Day 15). `is_wallet_trade=false` means a legacy 1-share
  // position from before the wallet existed — these render with a subtle
  // "legacy" badge and their unrealized_pnl_amount is per-share.
  is_wallet_trade?: boolean
  shares?: number
  position_size_usd?: number
  current_position_value?: number
}

export interface ClosedTrade {
  symbol: string
  pnl_pct: number
  pnl_amount?: number
  is_win: boolean
  source: string
  exit_reason?: string
  entry_score?: number
  exit_score?: number
  entry_date?: string
  exit_date?: string
  entry_price?: number
  exit_price?: number
  peak_price?: number
  exit_context?: string  // human-readable explanation of why it was sold
  // Day 26: full reasoning text for the expandable detail panel.
  // entry_thesis = Claude's synthesis at insert time (the why-bought).
  // thesis_last_reason = the most recent thesis re-eval (the why-sold,
  // OR the most-recent state for non-thesis exits).
  entry_thesis?: string
  thesis_last_reason?: string
  trade_horizon?: 'SHORT' | 'LONG'
  direction?: 'LONG' | 'SHORT'
  is_wallet_trade?: boolean
  shares?: number
  position_size_usd?: number
}

export interface WalletSummary {
  balance: number
  collateral_reserved: number
  total_value: number
  initial_deposit: number
  total_deposited: number
  total_withdrawn: number
  roi_pct: number
  open_positions_value: number
  updated_at?: string | null
}

// Must stay in sync with backend `wallet.TxnType` (app/services/wallet.py).
export type WalletTxnType =
  | 'DEPOSIT'
  | 'WITHDRAW'
  | 'BUY'
  | 'SELL'
  | 'SHORT_OPEN'
  | 'SHORT_COVER'
  | 'LEGACY_SELL'
  | 'LEGACY_COVER'
  | 'LEGACY_BASELINE'

export interface WalletTransaction {
  id: string
  transaction_type: WalletTxnType
  amount: number
  balance_after: number
  collateral_after: number
  trade_id?: string | null
  symbol?: string | null
  shares?: number | null
  price?: number | null
  description?: string | null
  created_at: string
}

export interface WalletTransactionList {
  transactions: WalletTransaction[]
  count: number
  limit: number
  offset: number
}

export interface WatchdogEvent {
  symbol: string
  event_type: 'ALERT' | 'CLOSE' | 'HOLD_THROUGH_DIP' | 'RECOVERY' | 'ESCALATION'
  price: number
  pnl_pct: number
  sentiment_label?: string
  action_taken: string
  in_watchlist: boolean
  notes?: string
  created_at: string
}

export interface WatchdogSummary {
  active: boolean
  positions_monitored: number
  recent_events: { symbol: string; event_type: string; created_at: string }[]
}

export interface VirtualSummary extends TrackStats {
  open_trades: VirtualTrade[]
  recent_closed: ClosedTrade[]
  watchlist: TrackStats
  brain: TrackStats
  watchdog?: WatchdogSummary
  wallet?: WalletSummary | null
}

// Format an ISO timestamp as a short ET date+time, e.g. "Apr 6, 10:02 AM".
// Used on closed-trade rows so users can see exactly when entry and exit
// fired (the brain scans at fixed minutes past the hour, so the time
// reveals which scan triggered each event). Day 27: added time component
// to answer Pedro's question "when did USAR get sold?" inline instead of
// requiring a DB query.
export function fmtShortDate(iso?: string): string {
  if (!iso) return '--'
  try {
    return new Date(iso).toLocaleString(intlLocale(), {
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      timeZone: DEFAULT_TIMEZONE,
    })
  } catch {
    return '--'
  }
}

export function getEventTypeColor(eventType: string, theme: Theme): string {
  const map: Record<string, string> = {
    CLOSE: theme.colors.down,
    ALERT: theme.colors.warning,
    ESCALATION: theme.colors.warning,
    HOLD_THROUGH_DIP: theme.colors.primary,
    RECOVERY: theme.colors.up,
  }
  return map[eventType] || theme.colors.textHint
}

// ── Wallet History (transactions ledger) ──
// Inline expansion, no modal. Collapsed by default so the card stays
// quiet when the user doesn't need it; expands to the latest 20 rows
// with "Load more" for pagination.

export const TXN_COLOR: Record<WalletTxnType, 'up' | 'down' | 'warning' | 'primary' | 'textHint'> = {
  DEPOSIT: 'up',
  WITHDRAW: 'down',
  BUY: 'primary',
  SELL: 'up',
  SHORT_OPEN: 'warning',
  SHORT_COVER: 'primary',
  LEGACY_SELL: 'up',
  LEGACY_COVER: 'up',
  LEGACY_BASELINE: 'textHint',
}

export function fmtTxnDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString(intlLocale(), {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      timeZone: DEFAULT_TIMEZONE,
    })
  } catch {
    return iso.slice(0, 16)
  }
}

export const TXN_PAGE_SIZE = 20

// Sell-type rows always carry positive `amount` (proceeds in) but the
// REALIZED P&L can be negative. Pulling P&L out of the description so
// the row visually surfaces win/loss instead of hiding it in prose.
export const PNL_REGEX = /P&L \$([+-]?[\d.]+)/

export function extractPnl(description: string | null | undefined): number | null {
  if (!description) return null
  const m = description.match(PNL_REGEX)
  if (!m) return null
  const parsed = parseFloat(m[1])
  return Number.isFinite(parsed) ? parsed : null
}

export const SELL_TYPES = new Set<WalletTxnType>(['SELL', 'SHORT_COVER', 'LEGACY_SELL', 'LEGACY_COVER'])
