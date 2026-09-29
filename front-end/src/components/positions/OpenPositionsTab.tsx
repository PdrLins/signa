'use client'

import { useState } from 'react'
import Link from 'next/link'
import { ChevronDown, ChevronUp, Target, ShieldAlert, Clock, Eye, Activity, Hash } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore, intlLocale } from '@/store/i18nStore'
import { relativeTime, DEFAULT_TIMEZONE, formatPct } from '@/lib/utils'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { getEventTypeColor, type ClosedTrade, type TrackStats, type VirtualSummary, type VirtualTrade, type WatchdogEvent } from './types'

interface OpenPositionsTabProps {
  data: VirtualSummary | undefined
  brain: TrackStats
  brainTrades: VirtualTrade[]
  brainClosed: ClosedTrade[]
  hasClosedData: boolean
  avgUnrealizedPnl: number
  watchdogEvents: WatchdogEvent[] | undefined
  monitoredSymbols: Set<string>
  discoveredSymbols: Set<string>
}

export function OpenPositionsTab({
  data, brain, brainTrades, brainClosed, hasClosedData, avgUnrealizedPnl,
  watchdogEvents, monitoredSymbols, discoveredSymbols,
}: OpenPositionsTabProps) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const [expandedSymbol, setExpandedSymbol] = useState<string | null>(null)
  const [watchdogExpandedSymbol, setWatchdogExpandedSymbol] = useState<string | null>(null)
  const [watchdogShowClosed, setWatchdogShowClosed] = useState(false)

  return (
    <div className="space-y-6">
    {/* Day-33 four-card stat row (image-6/dappr pattern adapted to dark).
        Each card has icon + label + big number + delta sub. Subtle
        rounded corners, surface bg, 1px border. Replaces the hairline-
        separated KPI strip. */}
    {(() => {
      const todayKey = new Date().toLocaleDateString('en-CA', { timeZone: DEFAULT_TIMEZONE })
      const isToday = (iso?: string) => !!iso && (new Date(iso).toLocaleDateString('en-CA', { timeZone: DEFAULT_TIMEZONE }) === todayKey)
      const todayClosed = brainClosed.filter(t => t.is_wallet_trade && isToday(t.exit_date))
      const todayPnl = todayClosed.reduce((sum, t) => sum + (t.pnl_amount ?? 0), 0)
      const todayCount = todayClosed.length

      const cards = [
        {
          icon: Clock,
          label: 'TODAY',
          value: todayCount === 0
            ? '\u2014'
            : `${todayPnl >= 0 ? '+$' : '-$'}${Math.abs(todayPnl).toFixed(2)}`,
          valueColor: todayCount === 0
            ? theme.colors.textHint
            : (todayPnl >= 0 ? theme.colors.up : theme.colors.down),
          sub: todayCount === 0 ? 'no closes yet' : `${todayCount} closed today`,
          subColor: theme.colors.textSub,
          accentColor: todayCount === 0
            ? theme.colors.textHint
            : (todayPnl >= 0 ? theme.colors.up : theme.colors.down),
        },
        {
          icon: Activity,
          label: 'OPEN',
          value: String(brain.open_count),
          valueColor: theme.colors.text,
          sub: brainTrades.length > 0 && avgUnrealizedPnl !== 0
            ? `avg ${avgUnrealizedPnl >= 0 ? '+' : ''}${formatPct(avgUnrealizedPnl)}%`
            : 'no live P&L',
          subColor: brainTrades.length > 0 && avgUnrealizedPnl !== 0
            ? (avgUnrealizedPnl >= 0 ? theme.colors.up : theme.colors.down)
            : theme.colors.textSub,
          accentColor: theme.colors.primary,
        },
        {
          icon: Target,
          label: 'WIN RATE',
          value: hasClosedData ? `${brain.win_rate.toFixed(0)}%` : '\u2014',
          valueColor: hasClosedData
            ? (brain.win_rate >= 60 ? theme.colors.up : brain.win_rate >= 50 ? theme.colors.warning : theme.colors.down)
            : theme.colors.textHint,
          sub: hasClosedData ? `${brain.wins}W / ${brain.losses}L` : 'no data',
          subColor: theme.colors.textSub,
          accentColor: hasClosedData
            ? (brain.win_rate >= 60 ? theme.colors.up : brain.win_rate >= 50 ? theme.colors.warning : theme.colors.down)
            : theme.colors.textHint,
        },
        {
          icon: Hash,
          label: 'TRADES',
          value: String(brain.closed_count + brain.open_count),
          valueColor: theme.colors.text,
          sub: `${brain.closed_count} closed`,
          subColor: theme.colors.textSub,
          accentColor: theme.colors.textSub,
        },
      ]

      return (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {cards.map((c, i) => {
            const Icon = c.icon
            return (
              <div
                key={i}
                className="rounded-2xl p-4 transition-colors"
                style={{
                  backgroundColor: theme.colors.surface,
                  border: `1px solid ${theme.colors.border}`,
                }}
              >
                <div className="flex items-center gap-2 mb-3">
                  <span
                    className="inline-flex items-center justify-center w-7 h-7 rounded-lg"
                    style={{
                      backgroundColor: c.accentColor + '18',
                      color: c.accentColor,
                    }}
                  >
                    <Icon size={14} />
                  </span>
                  <span
                    className="text-[9px] uppercase tracking-[0.18em]"
                    style={{ color: theme.colors.textHint, fontFamily: 'var(--font-mono)', fontWeight: 600 }}
                  >
                    {c.label}
                  </span>
                </div>
                <p
                  className="tabular-nums leading-none mb-2"
                  style={{
                    color: c.valueColor,
                    fontFamily: 'var(--font-mono)',
                    fontWeight: 600,
                    fontSize: 'clamp(1.5rem, 2.5vw, 2rem)',
                  }}
                >
                  {c.value}
                </p>
                <p
                  className="text-[11px] tabular-nums"
                  style={{ color: c.subColor, fontFamily: 'var(--font-mono)' }}
                >
                  {c.sub}
                </p>
              </div>
            )
          })}
        </div>
      )
    })()}

    {/* Win/loss baseline — Day-32: hairline instead of pill */}
    {hasClosedData && (
      <div className="flex items-center h-0.5 -mt-2">
        <div className="h-full" style={{ width: `${Math.max(5, brain.win_rate)}%`, backgroundColor: theme.colors.up }} />
        <div className="h-full" style={{ width: `${Math.max(5, 100 - brain.win_rate)}%`, backgroundColor: theme.colors.down }} />
      </div>
    )}

    {/* Watchdog Timeline */}
    {/* Watchdog Monitor Grid */}
    {(() => {
      // Build per-symbol watchdog state from events + open positions
      // Only include symbols that have actual watchdog events
      const evtsBySymbol: Record<string, WatchdogEvent[]> = {}
      for (const evt of (watchdogEvents || [])) {
        if (!evtsBySymbol[evt.symbol]) evtsBySymbol[evt.symbol] = []
        evtsBySymbol[evt.symbol].push(evt)
      }

      const getSymbolStatus = (evts: WatchdogEvent[]): { label: string; color: string; isClosed: boolean } => {
        const latest = evts[0]
        if (latest.event_type === 'CLOSE') return { label: 'closed', color: theme.colors.down, isClosed: true }
        if (latest.event_type === 'ALERT' || latest.event_type === 'ESCALATION')
          return { label: `${evts.length} alert${evts.length > 1 ? 's' : ''}`, color: theme.colors.warning, isClosed: false }
        if (latest.event_type === 'RECOVERY') return { label: 'recovered', color: theme.colors.up, isClosed: false }
        if (latest.event_type === 'HOLD_THROUGH_DIP') return { label: 'held dip', color: theme.colors.primary, isClosed: false }
        return { label: 'event', color: theme.colors.textHint, isClosed: false }
      }

      // Filter: hide closed positions unless toggled on
      const symbols = Object.keys(evtsBySymbol)
        .filter((sym) => {
          if (watchdogShowClosed) return true
          return !getSymbolStatus(evtsBySymbol[sym]).isClosed
        })
        .sort((a, b) => evtsBySymbol[b].length - evtsBySymbol[a].length)

      const closedCount = Object.values(evtsBySymbol).filter((evts) => getSymbolStatus(evts).isClosed).length

      return (
        <Card>
          <div className="flex items-center gap-1.5 mb-3">
            <Eye size={14} style={{ color: theme.colors.warning }} />
            <p className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: theme.colors.textSub }}>
              Watchdog — Monitoring {symbols.length} positions
            </p>
            <div className="flex items-center gap-2 ml-auto">
              {closedCount > 0 && (
                <button
                  onClick={() => setWatchdogShowClosed(!watchdogShowClosed)}
                  className="text-[8px] px-1.5 py-0.5 rounded-full transition-all"
                  style={{
                    backgroundColor: watchdogShowClosed ? theme.colors.textHint + '20' : 'transparent',
                    color: theme.colors.textHint,
                    border: `1px solid ${theme.colors.border}`,
                  }}
                >
                  {watchdogShowClosed ? 'Hide' : 'Show'} closed ({closedCount})
                </button>
              )}
              {data?.watchdog?.active && (
                <span className="text-[8px] px-1.5 py-0.5 rounded-full" style={{ backgroundColor: theme.colors.up + '15', color: theme.colors.up }}>
                  Active
                </span>
              )}
            </div>
          </div>

          {/* Symbol grid */}
          <div className="flex flex-wrap gap-1.5 mb-2">
            {symbols.map((sym) => {
              const evts = evtsBySymbol[sym]
              const status = getSymbolStatus(evts)
              const isExpanded = watchdogExpandedSymbol === sym

              return (
                <button
                  key={sym}
                  onClick={() => setWatchdogExpandedSymbol(isExpanded ? null : sym)}
                  className="flex items-center gap-1.5 px-2 py-1 rounded-lg text-[10px] font-medium transition-all"
                  style={{
                    backgroundColor: isExpanded ? status.color + '20' : theme.colors.surfaceAlt,
                    border: `1px solid ${isExpanded ? status.color + '40' : theme.colors.border}`,
                    color: theme.colors.text,
                  }}
                >
                  <span
                    className="w-1.5 h-1.5 rounded-full shrink-0"
                    style={{ backgroundColor: status.color }}
                  />
                  {sym}
                  {evts.length > 0 && (
                    <span className="text-[8px] tabular-nums" style={{ color: status.color }}>
                      {evts.length}
                    </span>
                  )}
                </button>
              )
            })}
          </div>

          {/* Expanded event history for selected symbol */}
          {watchdogExpandedSymbol && evtsBySymbol[watchdogExpandedSymbol] && (
            <div
              className="rounded-lg p-3 mt-1"
              style={{ backgroundColor: theme.colors.surfaceAlt, border: `1px solid ${theme.colors.border}` }}
            >
              {evtsBySymbol[watchdogExpandedSymbol].length === 0 ? (
                <p className="text-[10px]" style={{ color: theme.colors.textHint }}>
                  No watchdog events — position is healthy.
                </p>
              ) : (
                <div className="relative pl-4">
                  <div className="absolute left-[5px] top-1 bottom-1 w-px" style={{ backgroundColor: theme.colors.border }} />
                  <div className="space-y-2.5">
                    {evtsBySymbol[watchdogExpandedSymbol].map((evt, i) => {
                      const typeColor = getEventTypeColor(evt.event_type, theme)
                      const pnlColor = evt.pnl_pct >= 0 ? theme.colors.up : theme.colors.down
                      return (
                        <div key={i} className="relative">
                          <div
                            className="absolute -left-4 top-1 w-[10px] h-[10px] rounded-full border-2"
                            style={{ backgroundColor: theme.colors.surface, borderColor: typeColor }}
                          />
                          <div className="flex items-start justify-between gap-2">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="text-[9px] font-medium px-1.5 py-0.5 rounded" style={{ backgroundColor: typeColor + '15', color: typeColor }}>
                                {evt.event_type.replace(/_/g, ' ')}
                              </span>
                              {evt.sentiment_label && (
                                <span className="text-[9px]" style={{ color: theme.colors.textHint }}>{evt.sentiment_label}</span>
                              )}
                            </div>
                            <div className="flex items-center gap-2 shrink-0">
                              <span className="text-[10px] font-bold tabular-nums" style={{ color: pnlColor }}>
                                {evt.pnl_pct >= 0 ? '+' : ''}{formatPct(evt.pnl_pct)}%
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
              )}
            </div>
          )}
        </Card>
      )
    })()}

    {/* Day-32 editorial: Open positions as a section, not a card.
        Editorial header with serif label + mono count, hairline rule below. */}
    <section className="space-y-0">
      <div className="flex items-baseline justify-between pb-3" style={{ borderBottom: `1px solid ${theme.colors.border}` }}>
        <div className="flex items-baseline gap-3">
          <h2
            className="text-xl"
            style={{ color: theme.colors.text, fontWeight: 500 }}
          >
            Open positions
          </h2>
          <span
            className="text-xs tabular-nums"
            style={{ color: theme.colors.textHint, fontFamily: 'var(--font-mono)' }}
          >
            {String(brainTrades.length).padStart(2, '0')}
          </span>
        </div>
        {brainTrades.length > 0 && avgUnrealizedPnl !== 0 && (
          <span
            className="text-xs tabular-nums italic"
            style={{ color: avgUnrealizedPnl >= 0 ? theme.colors.up : theme.colors.down }}
          >
            avg{' '}
            <span style={{ fontFamily: 'var(--font-mono)', fontStyle: 'normal' }}>
              {avgUnrealizedPnl >= 0 ? '+' : ''}{formatPct(avgUnrealizedPnl)}%
            </span>
          </span>
        )}
      </div>

      {brainTrades.length === 0 ? (
        <p className="text-sm italic py-6" style={{ color: theme.colors.textHint }}>
          No open positions. The brain will pick tickers scoring 75+ with AI validation on the next scan.
        </p>
      ) : (
        <div>
          {brainTrades.map((vt) => {
            const isExpanded = expandedSymbol === vt.symbol
            const hasPnl = vt.unrealized_pnl_pct != null
            const pnlColor = hasPnl ? (vt.unrealized_pnl_pct! >= 0 ? theme.colors.up : theme.colors.down) : theme.colors.textSub

            return (
              <div key={vt.symbol} style={{ borderBottom: `1px solid ${theme.colors.border}` }}>
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
                    <span
                      className="text-base font-medium"
                      style={{ color: theme.colors.text, fontWeight: 500, letterSpacing: '0.01em' }}
                    >
                      {vt.symbol}
                    </span>
                    <Badge variant={vt.bucket === 'SAFE_INCOME' ? 'safe' : 'risk'}>
                      {vt.bucket === 'SAFE_INCOME' ? 'Safe' : 'Risk'}
                    </Badge>
                    <span
                      className="text-[8px] font-bold uppercase px-1.5 py-0.5 rounded"
                      style={{
                        backgroundColor: (vt.trade_horizon === 'LONG' ? theme.colors.primary : theme.colors.warning) + '18',
                        color: vt.trade_horizon === 'LONG' ? theme.colors.primary : theme.colors.warning,
                      }}
                    >
                      {vt.trade_horizon === 'LONG' ? t.brainPerf.long ?? 'Long' : t.brainPerf.short ?? 'Short'}
                    </span>
                    {vt.direction === 'SHORT' && (
                      <span
                        className="text-[8px] font-bold uppercase px-1.5 py-0.5 rounded"
                        style={{ backgroundColor: theme.colors.down + '18', color: theme.colors.down }}
                      >
                        ▼ {t.brainPerf.shortSell ?? 'Short Sell'}
                      </span>
                    )}
                    {(vt.consecutive_avoid_count ?? 0) > 0 && (
                      <span
                        className="text-[8px] font-bold uppercase px-1.5 py-0.5 rounded"
                        style={{ backgroundColor: theme.colors.warning + '18', color: theme.colors.warning }}
                        title={t.brainPerf.holdingThroughTooltip ?? 'LONG position holding through AVOID signal — waits for 2 consecutive AVOIDs before closing'}
                      >
                        {(t.brainPerf.holdingThrough ?? 'Hold {n}/2').replace('{n}', String(vt.consecutive_avoid_count))}
                      </span>
                    )}
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
                    {/* Wallet trades show "${size} ·" inline — makes the
                        position size visible at a glance. Legacy (1-share)
                        trades keep the plain price. */}
                    {vt.is_wallet_trade && vt.position_size_usd ? (
                      <span className="text-[10px] tabular-nums" style={{ color: theme.colors.textHint }}>
                        ${vt.position_size_usd.toLocaleString(intlLocale(), { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
                        {' @ '}${Number(vt.entry_price).toFixed(2)}
                      </span>
                    ) : (
                      <span className="text-[11px] tabular-nums" style={{ color: theme.colors.textHint }}>
                        ${Number(vt.entry_price).toFixed(2)}
                      </span>
                    )}
                    {hasPnl && (
                      <span className="text-[12px] font-bold tabular-nums" style={{ color: pnlColor }}>
                        {vt.unrealized_pnl_pct! >= 0 ? '+' : ''}{formatPct(vt.unrealized_pnl_pct!)}%
                        {vt.is_wallet_trade && vt.unrealized_pnl_amount != null && (
                          <span className="ml-1 text-[10px] font-normal" style={{ color: pnlColor }}>
                            ({vt.unrealized_pnl_amount >= 0 ? '+' : '-'}${Math.abs(vt.unrealized_pnl_amount).toFixed(2)})
                          </span>
                        )}
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
                      {vt.is_wallet_trade && vt.shares != null && (
                        <div className="flex items-center justify-between">
                          <span className="text-[10px]" style={{ color: theme.colors.textHint }}>Shares</span>
                          <span className="text-[11px] font-medium tabular-nums" style={{ color: theme.colors.text }}>
                            {vt.shares.toFixed(4)}
                          </span>
                        </div>
                      )}
                      {vt.is_wallet_trade && vt.position_size_usd != null && (
                        <div className="flex items-center justify-between">
                          <span className="text-[10px]" style={{ color: theme.colors.textHint }}>Invested</span>
                          <span className="text-[11px] font-medium tabular-nums" style={{ color: theme.colors.text }}>
                            ${vt.position_size_usd.toFixed(2)}
                          </span>
                        </div>
                      )}
                      {vt.is_wallet_trade && vt.current_position_value != null && (
                        <div className="flex items-center justify-between">
                          <span className="text-[10px]" style={{ color: theme.colors.textHint }}>Now worth</span>
                          <span className="text-[11px] font-medium tabular-nums" style={{ color: pnlColor }}>
                            ${vt.current_position_value.toFixed(2)}
                          </span>
                        </div>
                      )}
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
                    <div className="flex items-center gap-3 flex-wrap">
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
                      {vt.tier_reason && (
                        <span
                          className="text-[9px] font-medium px-1.5 py-0.5 rounded"
                          style={{
                            backgroundColor: (vt.tier_reason.includes('below_sma50') || vt.tier_reason.includes('overextended') ? theme.colors.warning : theme.colors.primary) + '15',
                            color: vt.tier_reason.includes('below_sma50') || vt.tier_reason.includes('overextended') ? theme.colors.warning : theme.colors.primary,
                          }}
                        >
                          {vt.tier_reason.includes('below_sma50') ? 'Below SMA50' : vt.tier_reason.includes('overextended') ? 'Overextended' : vt.tier_reason.replace(/_/g, ' ')}
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
    </section>
    </div>
  )
}
