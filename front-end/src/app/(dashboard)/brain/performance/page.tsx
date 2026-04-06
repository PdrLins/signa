'use client'

import { useQuery } from '@tanstack/react-query'
import Link from 'next/link'
import { useTheme } from '@/hooks/useTheme'
import { client } from '@/lib/api'
import { relativeTime } from '@/lib/utils'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { Skeleton } from '@/components/ui/Skeleton'
import { Sidebar } from '@/components/layout/Sidebar'
import { TrendingUp, TrendingDown, ChevronDown, ChevronUp, Brain, Target, ShieldAlert, Clock, Eye } from 'lucide-react'
import { useState, useMemo } from 'react'

// ── Types ──

interface TrackStats {
  open_count: number
  closed_count: number
  wins: number
  losses: number
  win_rate: number
  avg_return_pct: number
  total_return_pct: number
  avg_unrealized_pnl_pct?: number
  best_trade: { symbol: string; pnl_pct: number } | null
  worst_trade: { symbol: string; pnl_pct: number } | null
}

interface VirtualTrade {
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
}

interface ClosedTrade {
  symbol: string
  pnl_pct: number
  is_win: boolean
  source: string
  exit_reason?: string
  entry_score?: number
  exit_score?: number
}

interface WatchdogEvent {
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

interface WatchdogSummary {
  active: boolean
  positions_monitored: number
  recent_events: { symbol: string; event_type: string; created_at: string }[]
}

interface VirtualSummary extends TrackStats {
  open_trades: VirtualTrade[]
  recent_closed: ClosedTrade[]
  watchlist: TrackStats
  brain: TrackStats
  watchdog?: WatchdogSummary
}

// ── Small components ──

function StatBox({ label, value, sub, color, bgColor }: { label: string; value: string; sub?: string; color: string; bgColor: string }) {
  const theme = useTheme()
  return (
    <div className="rounded-xl px-4 py-3" style={{ backgroundColor: bgColor }}>
      <p className="text-[10px] uppercase tracking-wide mb-1" style={{ color: theme.colors.textHint }}>{label}</p>
      <p className="text-2xl font-bold tabular-nums" style={{ color }}>{value}</p>
      {sub && <p className="text-[10px] mt-0.5" style={{ color: theme.colors.textHint }}>{sub}</p>}
    </div>
  )
}

function ExitReasonBadge({ reason, theme }: { reason?: string; theme: ReturnType<typeof useTheme> }) {
  if (!reason) return null
  const config: Record<string, { label: string; color: string }> = {
    SIGNAL: { label: 'Signal', color: theme.colors.primary },
    STOP_HIT: { label: 'Stop hit', color: theme.colors.down },
    TARGET_HIT: { label: 'Target hit', color: theme.colors.up },
    TIME_EXPIRED: { label: 'Expired', color: theme.colors.warning },
    WATCHDOG_EXIT: { label: 'Watchdog', color: theme.colors.warning },
  }
  const c = config[reason] || { label: reason, color: theme.colors.textHint }
  return (
    <span className="text-[9px] font-medium px-1.5 py-0.5 rounded" style={{ backgroundColor: c.color + '15', color: c.color }}>
      {c.label}
    </span>
  )
}

function getEventTypeColor(eventType: string, theme: ReturnType<typeof useTheme>): string {
  const map: Record<string, string> = {
    CLOSE: theme.colors.down,
    ALERT: theme.colors.warning,
    ESCALATION: theme.colors.warning,
    HOLD_THROUGH_DIP: theme.colors.primary,
    RECOVERY: theme.colors.up,
  }
  return map[eventType] || theme.colors.textHint
}

// ── Main page ──

export default function BrainPerformancePage() {
  const theme = useTheme()
  const [expandedSymbol, setExpandedSymbol] = useState<string | null>(null)

  const { data, isLoading } = useQuery<VirtualSummary>({
    queryKey: ['stats', 'virtual-portfolio'],
    queryFn: async () => (await client.get<VirtualSummary>('/stats/virtual-portfolio')).data,
    staleTime: 30_000,
  })

  const { data: watchdogEvents } = useQuery<WatchdogEvent[]>({
    queryKey: ['stats', 'watchdog-events'],
    queryFn: async () => (await client.get<WatchdogEvent[]>('/stats/watchdog-events?limit=10')).data,
    staleTime: 30_000,
  })

  // Symbols with recent watchdog events — must be before early return (Rules of Hooks)
  const recentEvents = data?.watchdog?.recent_events
  const monitoredSymbols = useMemo(
    () => new Set(recentEvents?.map(e => e.symbol) ?? []),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [recentEvents?.length],
  )

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton width={250} height={28} />
        <div className="grid grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} width="100%" height={90} borderRadius={14} />)}
        </div>
        <Skeleton width="100%" height={300} borderRadius={14} />
      </div>
    )
  }

  const brain = data?.brain ?? { open_count: 0, closed_count: 0, wins: 0, losses: 0, win_rate: 0, avg_return_pct: 0, total_return_pct: 0, best_trade: null, worst_trade: null }
  const brainTrades = (data?.open_trades.filter(t => t.source === 'brain') ?? []).sort((a, b) => b.entry_score - a.entry_score)
  const brainClosed = data?.recent_closed.filter(t => t.source === 'brain') ?? []
  const hasClosedData = brain.closed_count > 0

  // Calculate total unrealized P&L across all open brain trades
  const totalUnrealizedPnl = brainTrades.reduce((sum, t) => sum + (t.unrealized_pnl_pct ?? 0), 0)
  const avgUnrealizedPnl = brainTrades.length > 0 ? totalUnrealizedPnl / brainTrades.length : 0

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2">
          <Brain size={22} style={{ color: theme.colors.warning }} />
          <h1 className="text-2xl font-bold" style={{ color: theme.colors.text }}>Brain Performance</h1>
        </div>
        <p className="text-sm mt-1" style={{ color: theme.colors.textSub }}>
          Autonomous picks proving the brain&apos;s accuracy with real market data.
        </p>
      </div>

      {/* Content + Sidebar */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_300px] gap-6 items-start">
        <div className="space-y-6">

          {/* Hero stats */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <StatBox
              label="Open Positions"
              value={String(brain.open_count)}
              sub={brainTrades.length > 0 && avgUnrealizedPnl !== 0
                ? `Avg P&L ${avgUnrealizedPnl >= 0 ? '+' : ''}${avgUnrealizedPnl.toFixed(1)}%`
                : undefined}
              color={theme.colors.text}
              bgColor={theme.colors.surfaceAlt}
            />
            <StatBox
              label="Win Rate"
              value={hasClosedData ? `${brain.win_rate.toFixed(0)}%` : '\u2014'}
              sub={hasClosedData ? `${brain.wins}W / ${brain.losses}L` : 'No closed trades yet'}
              color={hasClosedData ? (brain.win_rate >= 60 ? theme.colors.up : brain.win_rate >= 50 ? theme.colors.warning : theme.colors.down) : theme.colors.textSub}
              bgColor={theme.colors.surfaceAlt}
            />
            <StatBox
              label="Total Trades"
              value={String(brain.closed_count + brain.open_count)}
              sub={hasClosedData ? `${brain.closed_count} closed` : `${brain.open_count} open`}
              color={theme.colors.text}
              bgColor={theme.colors.surfaceAlt}
            />
            <StatBox
              label="Total Return"
              value={hasClosedData ? `${brain.total_return_pct >= 0 ? '+' : ''}${brain.total_return_pct.toFixed(1)}%` : '\u2014'}
              sub={hasClosedData ? `Avg ${brain.avg_return_pct >= 0 ? '+' : ''}${brain.avg_return_pct.toFixed(1)}% per trade` : 'Tracking...'}
              color={hasClosedData ? (brain.total_return_pct >= 0 ? theme.colors.up : theme.colors.down) : theme.colors.textSub}
              bgColor={theme.colors.surfaceAlt}
            />
          </div>

          {/* Win/loss bar */}
          {hasClosedData && (
            <div className="flex items-center gap-1">
              <div className="h-3 rounded-l-full transition-all" style={{ width: `${Math.max(5, brain.win_rate)}%`, backgroundColor: theme.colors.up }} />
              <div className="h-3 rounded-r-full transition-all" style={{ width: `${Math.max(5, 100 - brain.win_rate)}%`, backgroundColor: theme.colors.down }} />
            </div>
          )}

          {/* Best / Worst trades */}
          {hasClosedData && (brain.best_trade || brain.worst_trade) && (
            <div className="flex gap-6">
              {brain.best_trade && (
                <div className="flex items-center gap-2">
                  <TrendingUp size={14} style={{ color: theme.colors.up }} />
                  <span className="text-[11px]" style={{ color: theme.colors.textHint }}>Best</span>
                  <span className="text-[12px] font-semibold" style={{ color: theme.colors.text }}>{brain.best_trade.symbol}</span>
                  <span className="text-[12px] font-bold tabular-nums" style={{ color: theme.colors.up }}>+{brain.best_trade.pnl_pct.toFixed(1)}%</span>
                </div>
              )}
              {brain.worst_trade && (
                <div className="flex items-center gap-2">
                  <TrendingDown size={14} style={{ color: theme.colors.down }} />
                  <span className="text-[11px]" style={{ color: theme.colors.textHint }}>Worst</span>
                  <span className="text-[12px] font-semibold" style={{ color: theme.colors.text }}>{brain.worst_trade.symbol}</span>
                  <span className="text-[12px] font-bold tabular-nums" style={{ color: theme.colors.down }}>{brain.worst_trade.pnl_pct.toFixed(1)}%</span>
                </div>
              )}
            </div>
          )}

          {/* Open positions — brain picks */}
          <Card>
            <div className="flex items-center justify-between mb-3">
              <p className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: theme.colors.textSub }}>
                Open Positions ({brainTrades.length})
              </p>
              {brainTrades.length > 0 && avgUnrealizedPnl !== 0 && (
                <span className="text-[11px] font-bold tabular-nums" style={{ color: avgUnrealizedPnl >= 0 ? theme.colors.up : theme.colors.down }}>
                  {avgUnrealizedPnl >= 0 ? '+' : ''}{avgUnrealizedPnl.toFixed(1)}% avg
                </span>
              )}
            </div>

            {brainTrades.length === 0 ? (
              <p className="text-[11px]" style={{ color: theme.colors.textHint }}>
                No open positions. The brain will pick tickers scoring 72+ with AI analysis on the next scan.
              </p>
            ) : (
              <div className="space-y-1.5">
                {brainTrades.map((vt) => {
                  const isExpanded = expandedSymbol === vt.symbol
                  const hasPnl = vt.unrealized_pnl_pct != null
                  const pnlColor = hasPnl ? (vt.unrealized_pnl_pct! >= 0 ? theme.colors.up : theme.colors.down) : theme.colors.textSub

                  return (
                    <div key={vt.symbol} className="rounded-lg overflow-hidden" style={{ backgroundColor: theme.colors.surfaceAlt }}>
                      {/* Main row */}
                      <div
                        className="flex items-center justify-between py-2 px-3 cursor-pointer transition-opacity hover:opacity-80"
                        onClick={() => setExpandedSymbol(isExpanded ? null : vt.symbol)}
                      >
                        <div className="flex items-center gap-2">
                          <span className="text-[12px] font-semibold" style={{ color: theme.colors.text }}>{vt.symbol}</span>
                          <Badge variant={vt.bucket === 'SAFE_INCOME' ? 'safe' : 'risk'}>
                            {vt.bucket === 'SAFE_INCOME' ? 'Safe' : 'Risk'}
                          </Badge>
                          {monitoredSymbols.has(vt.symbol) && (
                            <span className="text-[9px] font-medium px-1.5 py-0.5 rounded flex items-center gap-0.5" style={{ backgroundColor: theme.colors.warning + '18', color: theme.colors.warning }}>
                              <Eye size={8} /> Monitoring
                            </span>
                          )}
                          {vt.signal_style === 'CONTRARIAN' && (
                            <span className="text-[9px] font-medium px-1.5 py-0.5 rounded" style={{ backgroundColor: theme.colors.warning + '18', color: theme.colors.warning }}>
                              Contrarian
                            </span>
                          )}
                          {isExpanded
                            ? <ChevronUp size={12} style={{ color: theme.colors.textHint }} />
                            : <ChevronDown size={12} style={{ color: theme.colors.textHint }} />
                          }
                        </div>
                        <div className="flex items-center gap-3">
                          <span className="text-[11px] tabular-nums" style={{ color: theme.colors.textHint }}>
                            ${Number(vt.entry_price).toFixed(2)}
                          </span>
                          {hasPnl && (
                            <span className="text-[12px] font-bold tabular-nums" style={{ color: pnlColor }}>
                              {vt.unrealized_pnl_pct! >= 0 ? '+' : ''}{vt.unrealized_pnl_pct!.toFixed(1)}%
                            </span>
                          )}
                          <span className="text-[11px] font-semibold tabular-nums px-1.5 py-0.5 rounded" style={{
                            backgroundColor: (vt.entry_score >= 75 ? theme.colors.up : theme.colors.warning) + '15',
                            color: vt.entry_score >= 75 ? theme.colors.up : theme.colors.warning,
                          }}>
                            {vt.entry_score}
                            {vt.current_score != null && vt.current_score !== vt.entry_score && (
                              <span style={{ color: vt.current_score > vt.entry_score ? theme.colors.up : theme.colors.down }}>
                                {' → '}{vt.current_score}
                              </span>
                            )}
                          </span>
                        </div>
                      </div>

                      {/* Expanded details */}
                      {isExpanded && (
                        <div className="px-3 pb-3 pt-1 space-y-2.5" style={{ borderTop: `1px solid ${theme.colors.border}` }}>
                          {/* Price grid */}
                          <div className="grid grid-cols-2 gap-x-4 gap-y-1">
                            <div className="flex items-center justify-between">
                              <span className="text-[10px]" style={{ color: theme.colors.textHint }}>Entry</span>
                              <span className="text-[11px] font-medium tabular-nums" style={{ color: theme.colors.text }}>${Number(vt.entry_price).toFixed(2)}</span>
                            </div>
                            {vt.current_price != null && (
                              <div className="flex items-center justify-between">
                                <span className="text-[10px]" style={{ color: theme.colors.textHint }}>Now</span>
                                <span className="text-[11px] font-medium tabular-nums" style={{ color: pnlColor }}>${vt.current_price.toFixed(2)}</span>
                              </div>
                            )}
                            {vt.target_price != null && (
                              <div className="flex items-center justify-between">
                                <span className="text-[10px] flex items-center gap-1" style={{ color: theme.colors.textHint }}>
                                  <Target size={9} /> Target
                                </span>
                                <span className="text-[11px] font-medium tabular-nums" style={{ color: theme.colors.up }}>${Number(vt.target_price).toFixed(2)}</span>
                              </div>
                            )}
                            {vt.stop_loss != null && (
                              <div className="flex items-center justify-between">
                                <span className="text-[10px] flex items-center gap-1" style={{ color: theme.colors.textHint }}>
                                  <ShieldAlert size={9} /> Stop
                                </span>
                                <span className="text-[11px] font-medium tabular-nums" style={{ color: theme.colors.down }}>${Number(vt.stop_loss).toFixed(2)}</span>
                              </div>
                            )}
                          </div>

                          {/* Meta row */}
                          <div className="flex items-center gap-3">
                            {vt.days_held != null && (
                              <span className="text-[10px] flex items-center gap-1" style={{ color: theme.colors.textHint }}>
                                <Clock size={9} /> {vt.days_held}d held
                              </span>
                            )}
                            {vt.risk_reward != null && (
                              <span className="text-[10px]" style={{ color: theme.colors.textHint }}>
                                R/R {vt.risk_reward.toFixed(1)}
                              </span>
                            )}
                            {vt.unrealized_pnl_amount != null && (
                              <span className="text-[10px] font-medium tabular-nums" style={{ color: pnlColor }}>
                                {vt.unrealized_pnl_amount >= 0 ? '+' : ''}${vt.unrealized_pnl_amount.toFixed(2)}
                              </span>
                            )}
                          </div>

                          {/* Reasoning */}
                          {vt.reasoning && (
                            <>
                              <div className="h-px" style={{ backgroundColor: theme.colors.border }} />
                              <p className="text-[10px] leading-relaxed" style={{ color: theme.colors.textSub }}>
                                {vt.reasoning}
                              </p>
                            </>
                          )}

                          <Link href={`/signals/${vt.symbol}`}>
                            <span className="text-[10px] font-medium" style={{ color: theme.colors.primary }}>
                              View full signal →
                            </span>
                          </Link>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </Card>

          {/* Closed trades */}
          <Card>
            <p className="text-[11px] font-semibold uppercase tracking-wide mb-3" style={{ color: theme.colors.textSub }}>
              Closed Trades ({brain.closed_count})
            </p>

            {brainClosed.length === 0 ? (
              <p className="text-[11px]" style={{ color: theme.colors.textHint }}>
                No closed trades yet. Trades close when they hit their target, stop loss, expire after 30 days, or the brain signals SELL.
              </p>
            ) : (
              <div className="space-y-1.5">
                {brainClosed.map((rc, i) => (
                  <Link key={i} href={`/signals/${rc.symbol}`}>
                    <div className="flex items-center justify-between py-2 px-3 rounded-lg transition-opacity hover:opacity-80" style={{ backgroundColor: theme.colors.surfaceAlt }}>
                      <div className="flex items-center gap-2">
                        {rc.is_win
                          ? <TrendingUp size={14} style={{ color: theme.colors.up }} />
                          : <TrendingDown size={14} style={{ color: theme.colors.down }} />
                        }
                        <span className="text-[12px] font-semibold" style={{ color: theme.colors.text }}>{rc.symbol}</span>
                        <ExitReasonBadge reason={rc.exit_reason} theme={theme} />
                        {rc.entry_score != null && (
                          <span className="text-[10px] tabular-nums" style={{ color: theme.colors.textHint }}>
                            {rc.entry_score}{rc.exit_score != null ? ` → ${rc.exit_score}` : ''}
                          </span>
                        )}
                      </div>
                      <span className="text-[13px] font-bold tabular-nums" style={{ color: rc.is_win ? theme.colors.up : theme.colors.down }}>
                        {rc.pnl_pct >= 0 ? '+' : ''}{rc.pnl_pct.toFixed(1)}%
                      </span>
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </Card>

          {/* Watchdog Activity */}
          {watchdogEvents && watchdogEvents.length > 0 && (
            <Card>
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-1.5">
                  <Eye size={14} style={{ color: theme.colors.warning }} />
                  <p className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: theme.colors.textSub }}>
                    Watchdog Activity ({watchdogEvents.length})
                  </p>
                </div>
                {data?.watchdog?.active && (
                  <span className="text-[9px] px-1.5 py-0.5 rounded" style={{ backgroundColor: theme.colors.up + '15', color: theme.colors.up }}>
                    Active
                  </span>
                )}
              </div>

              <div className="space-y-1.5">
                {watchdogEvents.map((evt, i) => {
                  const typeColor = getEventTypeColor(evt.event_type, theme)
                  const pnlColor = evt.pnl_pct >= 0 ? theme.colors.up : theme.colors.down

                  return (
                    <div key={i} className="flex items-center justify-between py-1.5 px-3 rounded-lg" style={{ backgroundColor: theme.colors.surfaceAlt }}>
                      <div className="flex items-center gap-2">
                        <span className="text-[12px] font-semibold" style={{ color: theme.colors.text }}>{evt.symbol}</span>
                        <span className="text-[9px] font-medium px-1.5 py-0.5 rounded" style={{ backgroundColor: typeColor + '15', color: typeColor }}>
                          {evt.event_type.replace(/_/g, ' ')}
                        </span>
                        {evt.in_watchlist && (
                          <span className="text-[8px] font-bold px-1 py-0.5 rounded" style={{ backgroundColor: theme.colors.primary + '15', color: theme.colors.primary }}>
                            WL
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-3">
                        <span className="text-[10px]" style={{ color: theme.colors.textHint }}>{evt.action_taken}</span>
                        <span className="text-[11px] font-bold tabular-nums" style={{ color: pnlColor }}>
                          {evt.pnl_pct >= 0 ? '+' : ''}{evt.pnl_pct.toFixed(1)}%
                        </span>
                        {evt.sentiment_label && (
                          <span className="text-[9px]" style={{ color: theme.colors.textHint }}>{evt.sentiment_label}</span>
                        )}
                        <span className="text-[9px]" style={{ color: theme.colors.textHint }}>{relativeTime(evt.created_at)}</span>
                      </div>
                    </div>
                  )
                })}
              </div>
            </Card>
          )}

        </div>
        <div className="sticky top-6 hidden lg:block">
          <Sidebar />
        </div>
      </div>
    </div>
  )
}
