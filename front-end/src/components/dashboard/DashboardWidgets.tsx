'use client'

import { useQuery } from '@tanstack/react-query'
import Link from 'next/link'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { client } from '@/lib/api'
import { relativeTime, formatPct, formatMoney } from '@/lib/utils'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { Skeleton } from '@/components/ui/Skeleton'
import { DollarSign, Brain, Zap, Bell, Briefcase, TrendingUp, Eye } from 'lucide-react'

// ─── Budget Summary ─────────────────────────────────

interface ProviderBudget {
  monthly_spend_usd: number
  monthly_limit_usd: number
  daily_calls: number
  budget_pct_used: number
  budget_remaining_usd: number
  is_free_tier: boolean
}

interface BudgetData {
  total_monthly_spend_usd: number
  providers: Record<string, ProviderBudget>
}

export function BudgetWidget() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)

  const { data, isLoading } = useQuery<BudgetData>({
    queryKey: ['health', 'budget'],
    queryFn: async () => (await client.get<BudgetData>('/health/budget')).data,
    staleTime: 30_000,
  })

  if (isLoading) return <Card><Skeleton width="100%" height={100} /></Card>
  if (!data) return null

  const claude = data.providers.claude
  const grok = data.providers.grok
  const remaining = (claude?.budget_remaining_usd ?? 0) + (grok?.budget_remaining_usd ?? 0)

  return (
    <Link href="/integrations" className="block h-full">
      <Card className="h-full">
        <div className="flex items-center justify-between mb-2.5">
          <div className="flex items-center gap-1.5">
            <DollarSign size={14} style={{ color: '#10B981' }} />
            <span className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: theme.colors.textSub }}>
              {t.integrations.budget}
            </span>
          </div>
          <span className="text-[11px] font-mono" style={{ color: theme.colors.text }}>
            ${data.total_monthly_spend_usd.toFixed(2)}
          </span>
        </div>

        {claude && !claude.is_free_tier && (
          <div className="mb-2">
            <div className="flex items-center justify-between mb-0.5">
              <div className="flex items-center gap-1.5">
                <Brain size={10} style={{ color: '#D97706' }} />
                <span className="text-[10px]" style={{ color: theme.colors.text }}>Claude</span>
              </div>
              <span className="text-[9px] tabular-nums" style={{ color: theme.colors.textHint }}>
                {claude.daily_calls} calls · ${claude.monthly_spend_usd.toFixed(2)}/${claude.monthly_limit_usd.toFixed(0)}
              </span>
            </div>
            <div className="w-full h-1 rounded-full overflow-hidden" style={{ backgroundColor: theme.colors.surfaceAlt }}>
              <div className="h-full rounded-full" style={{ width: `${Math.min(claude.budget_pct_used, 100)}%`, backgroundColor: claude.budget_pct_used > 80 ? theme.colors.down : '#D97706' }} />
            </div>
          </div>
        )}

        {grok && !grok.is_free_tier && (
          <div className="mb-2">
            <div className="flex items-center justify-between mb-0.5">
              <div className="flex items-center gap-1.5">
                <Zap size={10} style={{ color: '#1DA1F2' }} />
                <span className="text-[10px]" style={{ color: theme.colors.text }}>Grok</span>
              </div>
              <span className="text-[9px] tabular-nums" style={{ color: theme.colors.textHint }}>
                {grok.daily_calls} calls · ${grok.monthly_spend_usd.toFixed(2)}/${grok.monthly_limit_usd.toFixed(0)}
              </span>
            </div>
            <div className="w-full h-1 rounded-full overflow-hidden" style={{ backgroundColor: theme.colors.surfaceAlt }}>
              <div className="h-full rounded-full" style={{ width: `${Math.min(grok.budget_pct_used, 100)}%`, backgroundColor: grok.budget_pct_used > 80 ? theme.colors.down : '#1DA1F2' }} />
            </div>
          </div>
        )}

        <div className="flex items-center justify-between pt-1.5" style={{ borderTop: `1px solid ${theme.colors.border}15` }}>
          <span className="text-[9px]" style={{ color: theme.colors.textHint }}>{t.integrations.remaining}</span>
          <span className="text-[11px] font-bold tabular-nums" style={{ color: remaining < 2 ? theme.colors.down : theme.colors.up }}>${remaining.toFixed(2)}</span>
        </div>
      </Card>
    </Link>
  )
}


// ─── Recent Alerts ──────────────────────────────────

interface Alert {
  id: string
  alert_type: string
  message: string
  status: string
  created_at: string
}

export function AlertsWidget() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)

  const { data: alerts, isLoading } = useQuery<Alert[]>({
    queryKey: ['stats', 'recent-alerts'],
    queryFn: async () => (await client.get<Alert[]>('/stats/recent-alerts')).data,
    staleTime: 30_000,
  })

  if (isLoading) return <Card className="h-full"><Skeleton width="100%" height={100} /></Card>

  return (
    <Card className="h-full">
      <div className="flex items-center gap-1.5 mb-2.5">
        <Bell size={14} style={{ color: theme.colors.primary }} />
        <span className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: theme.colors.textSub }}>
          {t.overview.recentAlerts}
        </span>
      </div>

      {!alerts?.length ? (
        <p className="text-[11px]" style={{ color: theme.colors.textHint }}>{t.overview.noAlerts}</p>
      ) : (
        <div className="space-y-2">
          {alerts.slice(0, 3).map((a) => {
            const emoji = a.alert_type === 'GEM' ? '💎' : a.alert_type === 'WATCHLIST_SELL' ? '⚠️' : '📊'
            const time = new Date(a.created_at)
            const timeStr = time.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York' })
            // Extract ticker from message (between — and \n or end)
            const tickerMatch = a.message?.match(/— ([A-Z0-9.\-]+)/)
            const ticker = tickerMatch?.[1] || ''

            return (
              <div key={a.id} className="flex items-start gap-2">
                <span className="text-[12px] mt-0.5">{emoji}</span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between">
                    <span className="text-[11px] font-semibold truncate" style={{ color: theme.colors.text }}>
                      {ticker || a.alert_type.replace('_', ' ')}
                    </span>
                    <span className="text-[9px] shrink-0" style={{ color: theme.colors.textHint }}>{timeStr}</span>
                  </div>
                  <p className="text-[9px] truncate" style={{ color: theme.colors.textSub }}>
                    {a.alert_type.replace('_', ' ')}
                  </p>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </Card>
  )
}


// ─── Portfolio Snapshot ──────────────────────────────

interface PositionSummary {
  count: number
  positions: Array<{
    symbol: string
    entry_price: number
    shares: number
    bucket: string
    account_type: string
    last_signal_score: number | null
    last_signal_status: string | null
  }>
}

export function PortfolioWidget() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)

  const { data, isLoading } = useQuery<PositionSummary>({
    queryKey: ['stats', 'positions-summary'],
    queryFn: async () => (await client.get<PositionSummary>('/stats/positions-summary')).data,
    staleTime: 30_000,
  })

  if (isLoading) return <Card><Skeleton width="100%" height={100} /></Card>

  return (
    <Link href="/portfolio" className="block h-full">
      <Card className="h-full">
        <div className="flex items-center justify-between mb-2.5">
          <div className="flex items-center gap-1.5">
            <Briefcase size={14} style={{ color: theme.colors.primary }} />
            <span className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: theme.colors.textSub }}>
              {t.overview.portfolio}
            </span>
          </div>
          <span className="text-[11px] font-semibold" style={{ color: theme.colors.text }}>
            {data?.count ?? 0} {t.overview.openPositions}
          </span>
        </div>

        {!data?.positions?.length ? (
          <p className="text-[11px]" style={{ color: theme.colors.textHint }}>{t.overview.noPositions}</p>
        ) : (
          <div className="space-y-1.5">
            {data.positions.slice(0, 3).map((p) => (
              <div key={p.symbol} className="flex items-center justify-between py-1" style={{ borderBottom: `1px solid ${theme.colors.border}10` }}>
                <div className="flex items-center gap-2">
                  <span className="text-[11px] font-semibold" style={{ color: theme.colors.text }}>{p.symbol}</span>
                  {p.account_type && (
                    <Badge variant={p.account_type === 'TFSA' ? 'safe' : 'risk'}>{p.account_type}</Badge>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-[10px] tabular-nums" style={{ color: theme.colors.textSub }}>
                    {p.shares} @ ${Number(p.entry_price).toFixed(2)}
                  </span>
                  {p.last_signal_score && (
                    <span className="text-[10px] font-semibold tabular-nums" style={{ color: theme.colors.primary }}>
                      {p.last_signal_score}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </Link>
  )
}


// ─── Brain Performance (Virtual Portfolio) ───────────

interface TrackStats {
  open_count: number
  closed_count: number
  wins: number
  losses: number
  win_rate: number
  avg_return_pct: number
  total_return_pct: number
  best_trade: { symbol: string; pnl_pct: number } | null
  worst_trade: { symbol: string; pnl_pct: number } | null
}

interface WalletSummary {
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

interface VirtualSummary extends TrackStats {
  open_trades: Array<{ symbol: string; entry_price: number; entry_score: number; source: string }>
  recent_closed: Array<{ symbol: string; pnl_pct: number; is_win: boolean; source: string }>
  watchlist: TrackStats
  brain: TrackStats
  watchdog?: {
    active: boolean
    positions_monitored: number
    recent_events: { symbol: string; event_type: string; created_at: string }[]
  }
  wallet?: WalletSummary | null
}

export function BrainPerformanceWidget() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)

  const { data, isLoading } = useQuery<VirtualSummary>({
    queryKey: ['stats', 'virtual-portfolio'],
    queryFn: async () => (await client.get<VirtualSummary>('/stats/virtual-portfolio')).data,
    staleTime: 30_000,
  })

  if (isLoading) return <Card><Skeleton width="100%" height={140} /></Card>
  if (!data) return null

  const hasData = data.closed_count > 0 || data.open_count > 0

  const watchdogStatusText = (() => {
    if (!data.watchdog?.active) return null
    const alerts = data.watchdog.recent_events.filter(e => e.event_type === 'ALERT' || e.event_type === 'CLOSE')
    if (alerts.length > 0) {
      const latest = alerts[0]
      return `Watchdog: ${alerts.length} alert${alerts.length > 1 ? 's' : ''} on ${latest.symbol} (${relativeTime(latest.created_at)})`
    }
    return `Watchdog: active (${data.watchdog.positions_monitored} positions monitored)`
  })()

  return (
    <Link href="/brain/performance" className="block">
    <Card>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-1.5">
          <TrendingUp size={14} style={{ color: theme.colors.primary }} />
          <span className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: theme.colors.textSub }}>
            {t.overview.brainPerformance}
          </span>
        </div>
        {/* When the wallet has been funded, prefer wallet ROI over the
            per-trade aggregate — it's the number that actually describes
            capital performance. Day-21 fix: when wallet is NOT funded,
            fall back to avg_return_pct (per-trade arithmetic mean) instead
            of total_return_pct (which sums per-trade percentages and is
            mathematically meaningless across mixed cost bases). */}
        {data.wallet && data.wallet.initial_deposit > 0 ? (
          <span className="text-[11px] font-bold tabular-nums" style={{ color: data.wallet.roi_pct >= 0 ? theme.colors.up : theme.colors.down }}>
            {data.wallet.roi_pct >= 0 ? '+' : ''}{formatPct(data.wallet.roi_pct)}% ROI
          </span>
        ) : data.closed_count > 0 ? (
          <span className="text-[11px] font-bold tabular-nums" style={{ color: data.avg_return_pct >= 0 ? theme.colors.up : theme.colors.down }}>
            {data.avg_return_pct >= 0 ? '+' : ''}{data.avg_return_pct.toFixed(1)}% avg
          </span>
        ) : null}
      </div>

      {/* Portfolio row + breakdown. Portfolio = Wallet + Reserved +
          Holdings; the three sub-items explain what moves and what
          doesn't. Keeps the widget consistent with the wallet card on
          /brain/performance so users see the same mental model. */}
      {data.wallet && data.wallet.initial_deposit > 0 && (
        <div className="mb-3 pb-2" style={{ borderBottom: `1px solid ${theme.colors.border}30` }}>
          <div className="flex items-baseline justify-between mb-1.5">
            <span className="text-[9px] uppercase tracking-wide" style={{ color: theme.colors.textHint }}>
              {t.wallet?.portfolio ?? 'Portfolio'}
            </span>
            <span className="text-[14px] font-bold tabular-nums" style={{ color: theme.colors.text }}>
              {formatMoney(data.wallet.total_value)}
            </span>
          </div>
          <div className="flex items-baseline justify-between text-[10px] tabular-nums" style={{ color: theme.colors.textSub }}>
            <span>{t.wallet?.title ?? 'Wallet'}</span>
            <span>{formatMoney(data.wallet.balance)}</span>
          </div>
          <div className="flex items-baseline justify-between text-[10px] tabular-nums" style={{ color: theme.colors.textSub }}>
            <span>{t.wallet?.holdings ?? 'Holdings'}</span>
            <span>{formatMoney(data.wallet.open_positions_value)}</span>
          </div>
          {data.wallet.collateral_reserved > 0 && (
            <div className="flex items-baseline justify-between text-[10px] tabular-nums" style={{ color: theme.colors.textSub }}>
              <span>{t.wallet?.reserved ?? 'Reserved'}</span>
              <span>{formatMoney(data.wallet.collateral_reserved)}</span>
            </div>
          )}
        </div>
      )}

      {!hasData ? (
        <p className="text-[11px]" style={{ color: theme.colors.textHint }}>
          {t.overview.brainNoData}
        </p>
      ) : (
        <>
          <div className="grid grid-cols-3 gap-3 mb-3">
            <div>
              <p className="text-[9px] uppercase" style={{ color: theme.colors.textHint }}>{t.overview.winRateLabel}</p>
              <p className="text-[15px] font-bold" style={{ color: data.closed_count === 0 ? theme.colors.textSub : data.win_rate >= 60 ? theme.colors.up : data.win_rate >= 50 ? theme.colors.warning : theme.colors.down }}>
                {data.closed_count === 0 ? '\u2014' : `${data.win_rate.toFixed(0)}%`}
              </p>
            </div>
            <div>
              <p className="text-[9px] uppercase" style={{ color: theme.colors.textHint }}>{t.overview.trades}</p>
              <p className="text-[15px] font-bold" style={{ color: theme.colors.text }}>{data.closed_count}</p>
            </div>
            <div>
              <p className="text-[9px] uppercase" style={{ color: theme.colors.textHint }}>{t.overview.avgReturn}</p>
              <p className="text-[15px] font-bold" style={{ color: data.closed_count === 0 ? theme.colors.textSub : data.avg_return_pct >= 0 ? theme.colors.up : theme.colors.down }}>
                {data.closed_count === 0 ? '\u2014' : `${data.avg_return_pct >= 0 ? '+' : ''}${data.avg_return_pct.toFixed(1)}%`}
              </p>
            </div>
          </div>

          {data.closed_count > 0 && (
            <div className="flex items-center gap-1 mb-3">
              <div className="h-2 rounded-l-full" style={{ width: `${Math.max(5, data.win_rate)}%`, backgroundColor: theme.colors.up }} />
              <div className="h-2 rounded-r-full" style={{ width: `${Math.max(5, 100 - data.win_rate)}%`, backgroundColor: theme.colors.down }} />
            </div>
          )}

          {data.open_count > 0 && (
            <div className="pt-2" style={{ borderTop: `1px solid ${theme.colors.border}15` }}>
              {/* Watchlist picks */}
              {data.open_trades.filter(v => v.source === 'watchlist').length > 0 && (
                <div className="mb-2">
                  <p className="text-[9px] uppercase mb-1" style={{ color: theme.colors.textHint }}>
                    {t.overview.yourPicks} ({data.watchlist.open_count})
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {data.open_trades.filter(v => v.source === 'watchlist').map((vt) => (
                      <span key={vt.symbol} className="text-[10px] font-semibold px-1.5 py-0.5 rounded" style={{ backgroundColor: theme.colors.primary + '12', color: theme.colors.primary }}>
                        {vt.symbol}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              {/* Brain auto-picks */}
              {data.open_trades.filter(v => v.source === 'brain').length > 0 && (
                <div>
                  <p className="text-[9px] uppercase mb-1" style={{ color: theme.colors.textHint }}>
                    {t.overview.brainPicks} ({data.brain.open_count})
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {data.open_trades.filter(v => v.source === 'brain').map((vt) => (
                      <span key={vt.symbol} className="text-[10px] font-semibold px-1.5 py-0.5 rounded" style={{ backgroundColor: theme.colors.warning + '12', color: theme.colors.warning }}>
                        {vt.symbol}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Watchdog status */}
          {watchdogStatusText && (
            <div className="flex items-center gap-1.5 pt-2" style={{ borderTop: `1px solid ${theme.colors.border}15` }}>
              <Eye size={10} style={{ color: theme.colors.warning }} />
              <span className="text-[9px]" style={{ color: theme.colors.textHint }}>
                {watchdogStatusText}
              </span>
            </div>
          )}

          {data.recent_closed.length > 0 && (
            <div className="pt-2 mt-1" style={{ borderTop: `1px solid ${theme.colors.border}15` }}>
              <div className="flex flex-wrap gap-1.5">
                {data.recent_closed.slice(0, 5).map((rc) => (
                  <span key={`${rc.symbol}-${rc.pnl_pct}`} className="text-[10px] font-semibold px-1.5 py-0.5 rounded" style={{ backgroundColor: (rc.is_win ? theme.colors.up : theme.colors.down) + '12', color: rc.is_win ? theme.colors.up : theme.colors.down }}>
                    {rc.symbol} {rc.pnl_pct >= 0 ? '+' : ''}{rc.pnl_pct.toFixed(1)}%
                  </span>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </Card>
    </Link>
  )
}


// ─── Brain Tier Breakdown ─────────────────────────────

interface BrainTier {
  tier: 1 | 2 | 3
  label: string
  trust_pct: number
  open_count: number
  closed_count: number
  win_rate: number
  avg_pnl_pct: number
  best_pnl_pct: number | null
  worst_pnl_pct: number | null
}

interface BrainTierBreakdown {
  tiers: BrainTier[]
  total_brain_trades: number
  trades_with_tier: number
}

export function BrainTierBreakdownWidget() {
  const theme = useTheme()
  // Note: i18n keys for this widget are not yet in en.json/pt.json (gitignored).
  // Hardcoded English strings until they're added — TODO: i18n.

  const { data, isLoading } = useQuery<BrainTierBreakdown>({
    queryKey: ['stats', 'brain-tier-breakdown'],
    queryFn: async () => (await client.get<BrainTierBreakdown>('/stats/brain-tier-breakdown')).data,
    staleTime: 60_000,
  })

  if (isLoading) return <Card><Skeleton width="100%" height={120} /></Card>
  if (!data) return null

  const hasAnyTierData = data.trades_with_tier > 0

  return (
    <Card>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-1.5">
          <Brain size={14} style={{ color: theme.colors.primary }} />
          <span className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: theme.colors.textSub }}>
            Brain Trust Tiers
          </span>
        </div>
        {data.trades_with_tier > 0 && (
          <span className="text-[10px]" style={{ color: theme.colors.textHint }}>
            {data.trades_with_tier} tracked
          </span>
        )}
      </div>

      {!hasAnyTierData ? (
        <p className="text-[11px] leading-relaxed" style={{ color: theme.colors.textHint }}>
          No tier data yet. The brain will start tracking tiers as new trades open under the tiered trust model.
        </p>
      ) : (
        <div className="space-y-2">
          {data.tiers.map((tier) => {
            const tierColor = tier.tier === 1
              ? theme.colors.up
              : tier.tier === 2
              ? theme.colors.primary
              : theme.colors.warning
            const totalCount = tier.open_count + tier.closed_count
            const isActive = totalCount > 0
            const winRatePct = Math.round(tier.win_rate * 100)
            const winRateColor = tier.closed_count === 0
              ? theme.colors.textSub
              : tier.win_rate >= 0.6
              ? theme.colors.up
              : tier.win_rate >= 0.5
              ? theme.colors.warning
              : theme.colors.down
            return (
              <div
                key={tier.tier}
                className="flex items-center gap-3 py-1.5 px-2 rounded-lg"
                style={{
                  backgroundColor: isActive ? tierColor + '08' : 'transparent',
                  border: `1px solid ${isActive ? tierColor + '20' : theme.colors.border + '40'}`,
                }}
              >
                {/* Tier badge */}
                <div
                  className="flex items-center justify-center w-8 h-8 rounded-md shrink-0"
                  style={{ backgroundColor: tierColor + '15' }}
                >
                  <span className="text-[11px] font-bold tabular-nums" style={{ color: tierColor }}>
                    T{tier.tier}
                  </span>
                </div>

                {/* Label + size */}
                <div className="flex-1 min-w-0">
                  <p className="text-[11px] font-semibold truncate" style={{ color: theme.colors.text }}>
                    {tier.label}
                  </p>
                  <p className="text-[9px]" style={{ color: theme.colors.textHint }}>
                    {tier.trust_pct}% size · {tier.open_count} open · {tier.closed_count} closed
                  </p>
                </div>

                {/* Win rate + avg P&L */}
                <div className="text-right shrink-0">
                  <p className="text-[12px] font-bold tabular-nums" style={{ color: winRateColor }}>
                    {tier.closed_count === 0 ? '—' : `${winRatePct}%`}
                  </p>
                  <p
                    className="text-[9px] tabular-nums"
                    style={{
                      color: tier.closed_count === 0
                        ? theme.colors.textHint
                        : tier.avg_pnl_pct >= 0
                        ? theme.colors.up
                        : theme.colors.down,
                    }}
                  >
                    {tier.closed_count === 0
                      ? '—'
                      : `${tier.avg_pnl_pct >= 0 ? '+' : ''}${tier.avg_pnl_pct.toFixed(1)}% avg`}
                  </p>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </Card>
  )
}
