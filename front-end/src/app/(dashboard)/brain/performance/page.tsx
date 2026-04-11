'use client'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import Link from 'next/link'
import { useTheme } from '@/hooks/useTheme'
import { client } from '@/lib/api'
import { relativeTime, DEFAULT_TIMEZONE, formatPrice } from '@/lib/utils'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { Skeleton } from '@/components/ui/Skeleton'
import { Sidebar } from '@/components/layout/Sidebar'
import { TrendingUp, TrendingDown, ChevronDown, ChevronUp, Brain, Target, ShieldAlert, Clock, Eye, RefreshCw } from 'lucide-react'
import { useState, useMemo, useEffect, useCallback } from 'react'
import { useI18nStore } from '@/store/i18nStore'

// ── Track record types ──

interface TrackRecordRange {
  score_range: string
  trades: number
  win_rate: number
  avg_return_pct: number
}

interface TrackRecordData {
  ranges: TrackRecordRange[]
  total_trades: number
  overall_win_rate: number
  by_source: {
    brain: { ranges: TrackRecordRange[]; total_trades: number; win_rate: number }
    watchlist: { ranges: TrackRecordRange[]; total_trades: number; win_rate: number }
  }
}

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
  thesis_status?: string  // valid | weakening | invalid | null (legacy)
}

interface ClosedTrade {
  symbol: string
  pnl_pct: number
  is_win: boolean
  source: string
  exit_reason?: string
  entry_score?: number
  exit_score?: number
  entry_date?: string
  exit_date?: string
  entry_price?: number
  exit_price?: number
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

// Format an ISO timestamp as a short ET date, e.g. "Apr 6". Used so users
// can verify closed-trade entry/exit against external sources like yfinance.
function fmtShortDate(iso?: string): string {
  if (!iso) return '--'
  try {
    return new Date(iso).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      timeZone: DEFAULT_TIMEZONE,
    })
  } catch {
    return '--'
  }
}

// Format a P&L percentage with 2 decimals, avoiding "-0.00" for near-zero values.
function fmtPct(v: number): string {
  return Math.abs(v) < 0.005 ? '0.00' : v.toFixed(2)
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
    THESIS_INVALIDATED: { label: 'Brain Exit', color: theme.colors.warning },
    WATCHDOG_EXIT: { label: 'Watchdog', color: theme.colors.warning },
    TARGET_HIT: { label: 'Target Hit', color: theme.colors.up },
    STOP_HIT: { label: 'Stop Hit', color: theme.colors.down },
    PROFIT_TAKE: { label: 'Profit Take', color: theme.colors.up },
    TIME_EXPIRED: { label: 'Expired', color: theme.colors.warning },
    SIGNAL: { label: 'Signal', color: theme.colors.primary },
    ROTATION: { label: 'Rotated', color: theme.colors.primary },
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
  const t = useI18nStore((s) => s.t)
  const queryClient = useQueryClient()
  const [expandedSymbol, setExpandedSymbol] = useState<string | null>(null)
  const [autoRefresh, setAutoRefresh] = useState(false)
  const [refreshInterval] = useState(15)
  const [countdown, setCountdown] = useState(15)

  const { data, isLoading, isFetching } = useQuery<VirtualSummary>({
    queryKey: ['stats', 'virtual-portfolio'],
    queryFn: async () => (await client.get<VirtualSummary>('/stats/virtual-portfolio')).data,
    staleTime: 30_000,
    refetchInterval: autoRefresh ? refreshInterval * 1000 : false,
  })

  const { data: watchdogEvents } = useQuery<WatchdogEvent[]>({
    queryKey: ['stats', 'watchdog-events'],
    queryFn: async () => (await client.get<WatchdogEvent[]>('/stats/watchdog-events?limit=3')).data,
    staleTime: 30_000,
  })

  const { data: signalsData } = useQuery<{ signals: { symbol: string; is_discovered?: boolean }[] }>({
    queryKey: ['signals', 'discovered-check'],
    queryFn: async () => (await client.get('/signals?limit=200')).data,
    staleTime: 60_000,
  })

  const { data: trackRecord } = useQuery<TrackRecordData>({
    queryKey: ['signals', 'track-record'],
    queryFn: async () => (await client.get('/signals/track-record')).data,
    staleTime: 60_000,
  })

  // Auto-refresh countdown
  useEffect(() => {
    if (!autoRefresh) return
    setCountdown(refreshInterval)
    const timer = setInterval(() => {
      setCountdown((c) => {
        if (c <= 1) return refreshInterval
        return c - 1
      })
    }, 1000)
    return () => clearInterval(timer)
  }, [autoRefresh, refreshInterval])

  const handleRefresh = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['stats', 'virtual-portfolio'] })
    queryClient.invalidateQueries({ queryKey: ['stats', 'watchdog-events'] })
    setCountdown(refreshInterval)
  }, [queryClient, refreshInterval])

  // Symbols with recent watchdog events — must be before early return (Rules of Hooks)
  const recentEvents = data?.watchdog?.recent_events
  const monitoredSymbols = useMemo(
    () => new Set(recentEvents?.map(e => e.symbol) ?? []),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [recentEvents?.length],
  )

  // Symbols found via discovery (not in core universe)
  const discoveredSymbols = useMemo(
    () => new Set(signalsData?.signals?.filter(s => s.is_discovered).map(s => s.symbol) ?? []),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [signalsData?.signals?.length],
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
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Brain size={22} style={{ color: theme.colors.warning }} />
            <h1 className="text-2xl font-bold" style={{ color: theme.colors.text }}>Brain Performance</h1>
          </div>
          <p className="text-sm mt-1" style={{ color: theme.colors.textSub }}>
            Autonomous picks proving the brain&apos;s accuracy with real market data.
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {/* Auto-refresh toggle */}
          <button
            onClick={() => setAutoRefresh(!autoRefresh)}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[10px] font-semibold transition-all"
            style={{
              backgroundColor: autoRefresh ? theme.colors.primary + '15' : theme.colors.surfaceAlt,
              color: autoRefresh ? theme.colors.primary : theme.colors.textHint,
              border: `1px solid ${autoRefresh ? theme.colors.primary + '30' : theme.colors.border}`,
            }}
            aria-label="Toggle auto-refresh"
          >
            {autoRefresh ? `${countdown}s` : 'Auto'}
          </button>
          {/* Manual refresh */}
          <button
            onClick={handleRefresh}
            disabled={isFetching}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-semibold transition-opacity hover:opacity-80 disabled:opacity-50"
            style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.textSub }}
          >
            <RefreshCw size={12} className={isFetching ? 'animate-spin' : ''} />
            {isFetching ? 'Refreshing...' : 'Refresh'}
          </button>
        </div>
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
                ? `Avg P&L ${avgUnrealizedPnl >= 0 ? '+' : ''}${fmtPct(avgUnrealizedPnl)}%`
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
              value={hasClosedData ? `${brain.total_return_pct >= 0 ? '+' : ''}${fmtPct(brain.total_return_pct)}%` : '\u2014'}
              sub={hasClosedData ? `Avg ${brain.avg_return_pct >= 0 ? '+' : ''}${fmtPct(brain.avg_return_pct)}% per trade` : 'Tracking...'}
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
                  <span className="text-[12px] font-bold tabular-nums" style={{ color: theme.colors.up }}>+{fmtPct(brain.best_trade.pnl_pct)}%</span>
                </div>
              )}
              {brain.worst_trade && (
                <div className="flex items-center gap-2">
                  <TrendingDown size={14} style={{ color: theme.colors.down }} />
                  <span className="text-[11px]" style={{ color: theme.colors.textHint }}>Worst</span>
                  <span className="text-[12px] font-semibold" style={{ color: theme.colors.text }}>{brain.worst_trade.symbol}</span>
                  <span className="text-[12px] font-bold tabular-nums" style={{ color: theme.colors.down }}>{fmtPct(brain.worst_trade.pnl_pct)}%</span>
                </div>
              )}
            </div>
          )}

          {/* Watchdog Timeline */}
          {watchdogEvents && watchdogEvents.length > 0 && (
            <Card>
              <div className="flex items-center gap-1.5 mb-3">
                <Eye size={14} style={{ color: theme.colors.warning }} />
                <p className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: theme.colors.textSub }}>
                  Watchdog
                </p>
                {data?.watchdog?.active && (
                  <span className="text-[8px] px-1.5 py-0.5 rounded-full ml-auto" style={{ backgroundColor: theme.colors.up + '15', color: theme.colors.up }}>
                    Active
                  </span>
                )}
              </div>

              <div className="relative pl-4">
                {/* Timeline line */}
                <div className="absolute left-[5px] top-1 bottom-1 w-px" style={{ backgroundColor: theme.colors.border }} />

                <div className="space-y-3">
                  {watchdogEvents.map((evt, i) => {
                    const typeColor = getEventTypeColor(evt.event_type, theme)
                    const pnlColor = evt.pnl_pct >= 0 ? theme.colors.up : theme.colors.down

                    return (
                      <div key={i} className="relative">
                        {/* Timeline dot */}
                        <div
                          className="absolute -left-4 top-1 w-[10px] h-[10px] rounded-full border-2"
                          style={{ backgroundColor: theme.colors.surface, borderColor: typeColor }}
                        />

                        <div className="flex items-start justify-between gap-2">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-[11px] font-semibold" style={{ color: theme.colors.text }}>{evt.symbol}</span>
                            <span className="text-[9px] font-medium px-1.5 py-0.5 rounded" style={{ backgroundColor: typeColor + '15', color: typeColor }}>
                              {evt.event_type.replace(/_/g, ' ')}
                            </span>
                            {evt.in_watchlist && (
                              <span className="text-[8px] font-bold px-1 py-0.5 rounded" style={{ backgroundColor: theme.colors.primary + '15', color: theme.colors.primary }}>
                                WL
                              </span>
                            )}
                            {evt.sentiment_label && (
                              <span className="text-[9px]" style={{ color: theme.colors.textHint }}>{evt.sentiment_label}</span>
                            )}
                          </div>
                          <div className="flex items-center gap-2 shrink-0">
                            <span className="text-[11px] font-bold tabular-nums" style={{ color: pnlColor }}>
                              {evt.pnl_pct >= 0 ? '+' : ''}{fmtPct(evt.pnl_pct)}%
                            </span>
                            <span className="text-[9px]" style={{ color: theme.colors.textHint }}>{relativeTime(evt.created_at)}</span>
                          </div>
                        </div>

                        <p className="text-[9px] mt-0.5" style={{ color: theme.colors.textHint }}>
                          {evt.action_taken}
                        </p>
                      </div>
                    )
                  })}
                </div>
              </div>
            </Card>
          )}

          {/* Open positions — brain picks */}
          <Card>
            <div className="flex items-center justify-between mb-3">
              <p className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: theme.colors.textSub }}>
                Open Positions ({brainTrades.length})
              </p>
              {brainTrades.length > 0 && avgUnrealizedPnl !== 0 && (
                <span className="text-[11px] font-bold tabular-nums" style={{ color: avgUnrealizedPnl >= 0 ? theme.colors.up : theme.colors.down }}>
                  {avgUnrealizedPnl >= 0 ? '+' : ''}{fmtPct(avgUnrealizedPnl)}% avg
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
                        <div className="flex items-center gap-2 min-w-0">
                          {/* Thesis status dot: green=valid, yellow=weakening, gray=untracked */}
                          <span
                            className="w-2 h-2 rounded-full shrink-0"
                            title={vt.thesis_status === 'valid' ? 'Thesis valid' : vt.thesis_status === 'weakening' ? 'Thesis weakening' : 'No thesis tracking'}
                            style={{
                              backgroundColor: vt.thesis_status === 'valid' ? theme.colors.up
                                : vt.thesis_status === 'weakening' ? theme.colors.warning
                                : theme.colors.border,
                            }}
                          />
                          <span className="text-[12px] font-semibold" style={{ color: theme.colors.text }}>{vt.symbol}</span>
                          <Badge variant={vt.bucket === 'SAFE_INCOME' ? 'safe' : 'risk'}>
                            {vt.bucket === 'SAFE_INCOME' ? 'Safe' : 'Risk'}
                          </Badge>
                          {monitoredSymbols.has(vt.symbol) && (
                            <span className="text-[9px] font-medium px-1.5 py-0.5 rounded flex items-center gap-0.5" style={{ backgroundColor: theme.colors.warning + '18', color: theme.colors.warning }}>
                              <Eye size={8} /> Monitoring
                            </span>
                          )}
                          {discoveredSymbols.has(vt.symbol) && (
                            <span className="text-[9px] font-medium px-1.5 py-0.5 rounded" style={{ backgroundColor: theme.colors.primary + '18', color: theme.colors.primary }}>
                              Discovered
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
                        <div className="flex items-center gap-2">
                          {vt.days_held != null && (
                            <span className="text-[9px] tabular-nums px-1 py-0.5 rounded" style={{ color: theme.colors.textHint, backgroundColor: theme.colors.surfaceAlt }}>
                              {vt.days_held}d
                            </span>
                          )}
                          <span className="text-[11px] tabular-nums" style={{ color: theme.colors.textHint }}>
                            ${Number(vt.entry_price).toFixed(2)}
                          </span>
                          {hasPnl && (
                            <span className="text-[12px] font-bold tabular-nums" style={{ color: pnlColor }}>
                              {vt.unrealized_pnl_pct! >= 0 ? '+' : ''}{fmtPct(vt.unrealized_pnl_pct!)}%
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
                {brainClosed.map((rc, i) => {
                  const daysHeld = rc.entry_date && rc.exit_date
                    ? Math.max(1, Math.round((new Date(rc.exit_date).getTime() - new Date(rc.entry_date).getTime()) / 86400000))
                    : null
                  return (
                    <Link key={i} href={`/signals/${rc.symbol}`}>
                      <div className="flex items-start justify-between py-2 px-3 rounded-lg transition-opacity hover:opacity-80" style={{ backgroundColor: theme.colors.surfaceAlt }}>
                        <div className="flex flex-col gap-1 min-w-0">
                          <div className="flex items-center gap-2">
                            {rc.is_win
                              ? <TrendingUp size={14} style={{ color: theme.colors.up }} />
                              : <TrendingDown size={14} style={{ color: theme.colors.down }} />
                            }
                            <span className="text-[12px] font-semibold" style={{ color: theme.colors.text }}>{rc.symbol}</span>
                            <ExitReasonBadge reason={rc.exit_reason} theme={theme} />
                            {daysHeld != null && (
                              <span className="text-[9px] tabular-nums px-1 py-0.5 rounded" style={{ color: theme.colors.textHint, backgroundColor: theme.colors.surface }}>
                                {daysHeld}d
                              </span>
                            )}
                            {rc.entry_score != null && (
                              <span className="text-[10px] tabular-nums" style={{ color: theme.colors.textHint }}>
                                {rc.entry_score}{rc.exit_score != null ? ` → ${rc.exit_score}` : ''}
                              </span>
                            )}
                          </div>
                          <div className="text-[10px] tabular-nums pl-[22px]" style={{ color: theme.colors.textHint }}>
                            {fmtShortDate(rc.entry_date)} {formatPrice(rc.entry_price)} → {fmtShortDate(rc.exit_date)} {formatPrice(rc.exit_price)}
                          </div>
                        </div>
                        <span className="text-[13px] font-bold tabular-nums shrink-0" style={{ color: rc.is_win ? theme.colors.up : theme.colors.down }}>
                          {rc.pnl_pct >= 0 ? '+' : ''}{fmtPct(rc.pnl_pct)}%
                        </span>
                      </div>
                    </Link>
                  )
                })}
              </div>
            )}
          </Card>

          {/* Track Record by Score Range */}
          {trackRecord && trackRecord.total_trades > 0 && (
            <Card>
              <p className="text-[11px] font-semibold uppercase tracking-wide mb-3" style={{ color: theme.colors.textSub }}>
                {t.brainPerf.trackRecord}
              </p>
              <p className="text-[10px] mb-4" style={{ color: theme.colors.textHint }}>
                {t.brainPerf.trackRecordDesc} ({trackRecord.total_trades} {t.brainPerf.trades.toLowerCase()})
              </p>

              {/* Table header */}
              <div className="grid grid-cols-4 gap-2 pb-2 mb-1" style={{ borderBottom: `1px solid ${theme.colors.border}` }}>
                <p className="text-[9px] font-semibold uppercase tracking-wide" style={{ color: theme.colors.textHint }}>{t.brainPerf.scoreRange}</p>
                <p className="text-[9px] font-semibold uppercase tracking-wide text-center" style={{ color: theme.colors.textHint }}>{t.brainPerf.trades}</p>
                <p className="text-[9px] font-semibold uppercase tracking-wide text-center" style={{ color: theme.colors.textHint }}>{t.stats.winRate}</p>
                <p className="text-[9px] font-semibold uppercase tracking-wide text-right" style={{ color: theme.colors.textHint }}>{t.brainPerf.avgReturn}</p>
              </div>

              {/* Table rows */}
              <div className="space-y-0.5">
                {trackRecord.ranges.map((row) => (
                  <div
                    key={row.score_range}
                    className="grid grid-cols-4 gap-2 py-2 rounded-lg px-1"
                    style={{ backgroundColor: row.trades > 0 ? theme.colors.surfaceAlt : 'transparent' }}
                  >
                    <p className="text-[11px] font-semibold tabular-nums" style={{ color: theme.colors.text }}>{row.score_range}</p>
                    <p className="text-[11px] tabular-nums text-center" style={{ color: theme.colors.textSub }}>{row.trades}</p>
                    <p className="text-[11px] font-semibold tabular-nums text-center" style={{
                      color: row.trades === 0 ? theme.colors.textHint : row.win_rate >= 60 ? theme.colors.up : row.win_rate >= 50 ? theme.colors.warning : theme.colors.down,
                    }}>
                      {row.trades === 0 ? '\u2014' : `${row.win_rate.toFixed(0)}%`}
                    </p>
                    <p className="text-[11px] font-semibold tabular-nums text-right" style={{
                      color: row.trades === 0 ? theme.colors.textHint : row.avg_return_pct >= 0 ? theme.colors.up : theme.colors.down,
                    }}>
                      {row.trades === 0 ? '\u2014' : `${row.avg_return_pct >= 0 ? '+' : ''}${fmtPct(row.avg_return_pct)}%`}
                    </p>
                  </div>
                ))}
              </div>

              {/* Overall summary */}
              <div className="grid grid-cols-4 gap-2 pt-2 mt-1 px-1" style={{ borderTop: `1px solid ${theme.colors.border}` }}>
                <p className="text-[11px] font-bold" style={{ color: theme.colors.text }}>{t.brainPerf.overall}</p>
                <p className="text-[11px] font-bold tabular-nums text-center" style={{ color: theme.colors.text }}>{trackRecord.total_trades}</p>
                <p className="text-[11px] font-bold tabular-nums text-center" style={{
                  color: trackRecord.overall_win_rate >= 60 ? theme.colors.up : trackRecord.overall_win_rate >= 50 ? theme.colors.warning : theme.colors.down,
                }}>
                  {trackRecord.overall_win_rate.toFixed(0)}%
                </p>
                <p className="text-[11px] text-right" style={{ color: theme.colors.textHint }}></p>
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
