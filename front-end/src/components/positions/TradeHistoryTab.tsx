'use client'

import { useState } from 'react'
import Link from 'next/link'
import { TrendingUp, TrendingDown } from 'lucide-react'
import { ResponsiveContainer, AreaChart, Area, Tooltip as RechartsTooltip, ReferenceLine } from 'recharts'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore, intlLocale } from '@/store/i18nStore'
import type { Theme } from '@/lib/themes'
import { DEFAULT_TIMEZONE, formatPrice, formatPct } from '@/lib/utils'
import { Card } from '@/components/ui/Card'
import { fmtShortDate, type ClosedTrade, type TrackRecordData, type TrackStats, type VirtualSummary } from './types'

function ExitReasonBadge({ reason, theme }: { reason?: string; theme: Theme }) {
  if (!reason) return null
  const config: Record<string, { label: string; color: string }> = {
    THESIS_INVALIDATED: { label: 'Brain Exit', color: theme.colors.warning },
    WATCHDOG_EXIT: { label: 'Watchdog', color: theme.colors.warning },
    TARGET_HIT: { label: 'Target Hit', color: theme.colors.up },
    STOP_HIT: { label: 'Stop Hit', color: theme.colors.down },
    TRAILING_STOP: { label: 'Trailing Stop', color: theme.colors.up },
    QUALITY_PRUNE: { label: 'Pruned', color: theme.colors.warning },
    STAGNATION_PRUNE: { label: 'Stagnant', color: theme.colors.warning },
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

interface TradeHistoryTabProps {
  data: VirtualSummary | undefined
  brain: TrackStats
  brainClosed: ClosedTrade[]
  trackRecord: TrackRecordData | undefined
}

export function TradeHistoryTab({ data, brain, brainClosed, trackRecord }: TradeHistoryTabProps) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const [closedVisibleCount, setClosedVisibleCount] = useState(5)
  const [expandedClosedKey, setExpandedClosedKey] = useState<string | null>(null)
  const [chartRange, setChartRange] = useState<'1W' | '1M' | '3M' | 'ALL'>('ALL')

  return (
    <div className="space-y-6">
    {/* Day-32 chart: cumulative realized P&L since first wallet trade.
        Editorial chart — no axes, no grid, just the shape of the curve.
        Tells the recovery story visually: the V from -$108 trough to today.
        Day-33: added 1W/1M/3M/ALL time-range tabs (image-5 pattern). */}
    {(() => {
      const wallet = data?.wallet
      if (!wallet || wallet.initial_deposit <= 0) return null
      // brainClosed comes DESC from API — reverse to chronological.
      // Filter to wallet trades only (legacy = per-share, not summable).
      const allWalletClosed = [...brainClosed]
        .filter(t => t.is_wallet_trade && t.exit_date && t.pnl_amount != null)
        .sort((a, b) => (a.exit_date! < b.exit_date! ? -1 : 1))
      if (allWalletClosed.length < 2) return null

      // Apply time-range filter. Cumulative is computed from the FULL
      // history first so the curve's starting baseline is the actual
      // pre-range cumulative (otherwise filtered window would always
      // start at zero). Then slice to the visible window.
      const now = Date.now()
      const rangeMs: Record<typeof chartRange, number | null> = {
        '1W': 7 * 24 * 3600 * 1000,
        '1M': 30 * 24 * 3600 * 1000,
        '3M': 90 * 24 * 3600 * 1000,
        'ALL': null,
      }
      const cutoffMs = rangeMs[chartRange]
      const walletClosed = cutoffMs == null
        ? allWalletClosed
        : allWalletClosed.filter(t => now - new Date(t.exit_date!).getTime() <= cutoffMs)
      if (walletClosed.length < 2) {
        // Not enough data in this range — render the full set but flag it
        return (
          <div className="pb-6" style={{ borderBottom: `1px solid ${theme.colors.border}` }}>
            <div className="flex items-baseline justify-between mb-4">
              <h2 className="text-xl" style={{ color: theme.colors.text, fontWeight: 500 }}>
                Cumulative P&amp;L
              </h2>
              <div className="flex items-center gap-1">
                {(['1W', '1M', '3M', 'ALL'] as const).map(r => (
                  <button
                    key={r}
                    onClick={() => setChartRange(r)}
                    className="text-[10px] uppercase tracking-[0.12em] px-2.5 py-1 rounded transition-colors"
                    style={{
                      color: chartRange === r ? theme.colors.primary : theme.colors.textHint,
                      backgroundColor: chartRange === r ? theme.colors.primary + '15' : 'transparent',
                      fontFamily: 'var(--font-mono)',
                      fontWeight: chartRange === r ? 600 : 500,
                    }}
                  >
                    {r}
                  </button>
                ))}
              </div>
            </div>
            <p className="text-sm italic py-8 text-center" style={{ color: theme.colors.textHint }}>
              Not enough closes in this range. Showing wider window:
            </p>
          </div>
        )
      }

      let running = 0
      const series = walletClosed.map(t => {
        running += (t.pnl_amount ?? 0)
        return {
          date: t.exit_date!,
          label: new Date(t.exit_date!).toLocaleDateString(intlLocale(), { month: 'short', day: 'numeric', timeZone: DEFAULT_TIMEZONE }),
          cumulative: parseFloat(running.toFixed(2)),
          symbol: t.symbol,
          tradePnl: t.pnl_amount ?? 0,
        }
      })
      const current = series[series.length - 1].cumulative
      const peak = Math.max(...series.map(p => p.cumulative))
      const trough = Math.min(...series.map(p => p.cumulative))
      const isUp = current >= 0
      const lineColor = isUp ? theme.colors.up : theme.colors.down

      return (
        <div className="pb-6" style={{ borderBottom: `1px solid ${theme.colors.border}` }}>
          <div className="flex items-baseline justify-between mb-4 flex-wrap gap-3">
            <div className="flex items-baseline gap-3">
              <h2 className="text-xl" style={{ color: theme.colors.text, fontWeight: 500 }}>
                Cumulative P&amp;L
              </h2>
              <span className="text-xs" style={{ color: theme.colors.textHint, fontFamily: 'var(--font-mono)' }}>
                {walletClosed.length} CLOSES
              </span>
            </div>
            <div className="flex items-center gap-1 order-3 md:order-2">
              {(['1W', '1M', '3M', 'ALL'] as const).map(r => (
                <button
                  key={r}
                  onClick={() => setChartRange(r)}
                  className="text-[10px] uppercase tracking-[0.12em] px-2.5 py-1 rounded transition-colors"
                  style={{
                    color: chartRange === r ? theme.colors.primary : theme.colors.textHint,
                    backgroundColor: chartRange === r ? theme.colors.primary + '15' : 'transparent',
                    fontFamily: 'var(--font-mono)',
                    fontWeight: chartRange === r ? 600 : 500,
                  }}
                >
                  {r}
                </button>
              ))}
            </div>
            <div className="flex items-baseline gap-6 text-xs order-2 md:order-3" style={{ fontFamily: 'var(--font-mono)' }}>
              <div>
                <span style={{ color: theme.colors.textHint }}>TROUGH </span>
                <span style={{ color: theme.colors.down }}>${trough.toFixed(2)}</span>
              </div>
              <div>
                <span style={{ color: theme.colors.textHint }}>PEAK </span>
                <span style={{ color: theme.colors.up }}>${peak.toFixed(2)}</span>
              </div>
              <div>
                <span style={{ color: theme.colors.textHint }}>NOW </span>
                <span style={{ color: lineColor }}>{current >= 0 ? '+' : ''}${current.toFixed(2)}</span>
              </div>
            </div>
          </div>
          {/* Day-33 split-at-zero: stops in the gradient at the $0 line
              so green renders above and red renders below. Without this
              the entire area was lineColor — visually misleading when
              the curve crosses zero. Offset is peak / (peak - trough);
              fully-positive curves get offset=1 (all green), fully-
              negative get offset=0 (all red). */}
          {(() => {
            const gradientStop = peak <= 0
              ? 0
              : trough >= 0
                ? 1
                : peak / (peak - trough)
            return (
          <ResponsiveContainer width="100%" height={180}>
            <AreaChart data={series} margin={{ top: 4, right: 4, left: 4, bottom: 4 }}>
              <defs>
                <linearGradient id="pnlFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0" stopColor={theme.colors.up} stopOpacity={0.35} />
                  <stop offset={gradientStop} stopColor={theme.colors.up} stopOpacity={0} />
                  <stop offset={gradientStop} stopColor={theme.colors.down} stopOpacity={0} />
                  <stop offset="1" stopColor={theme.colors.down} stopOpacity={0.35} />
                </linearGradient>
                <linearGradient id="pnlStroke" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0" stopColor={theme.colors.up} />
                  <stop offset={gradientStop} stopColor={theme.colors.up} />
                  <stop offset={gradientStop} stopColor={theme.colors.down} />
                  <stop offset="1" stopColor={theme.colors.down} />
                </linearGradient>
              </defs>
              <ReferenceLine
                y={0}
                stroke={theme.colors.border}
                strokeWidth={1}
                strokeDasharray="3 3"
              />
              <Area
                type="monotone"
                dataKey="cumulative"
                stroke="url(#pnlStroke)"
                strokeWidth={1.75}
                fill="url(#pnlFill)"
                isAnimationActive={false}
                dot={false}
                activeDot={{ r: 3, stroke: lineColor, strokeWidth: 1, fill: theme.colors.bg }}
              />
              <RechartsTooltip
                cursor={{ stroke: theme.colors.border, strokeWidth: 1 }}
                content={({ active, payload }) => {
                  if (!active || !payload || !payload[0]) return null
                  const p = payload[0].payload as { label: string; cumulative: number; symbol: string; tradePnl: number }
                  return (
                    <div
                      className="px-3 py-2 text-xs"
                      style={{
                        backgroundColor: theme.colors.surface,
                        border: `1px solid ${theme.colors.border}`,
                        fontFamily: 'var(--font-mono)',
                      }}
                    >
                      <div style={{ color: theme.colors.textHint, fontSize: 10, letterSpacing: '0.12em' }}>
                        {p.label.toUpperCase()}
                      </div>
                      <div style={{ color: theme.colors.text, marginTop: 4 }}>
                        {p.symbol}{' '}
                        <span style={{ color: p.tradePnl >= 0 ? theme.colors.up : theme.colors.down }}>
                          {p.tradePnl >= 0 ? '+' : ''}${p.tradePnl.toFixed(2)}
                        </span>
                      </div>
                      <div style={{ color: theme.colors.textSub, marginTop: 2 }}>
                        cum{' '}
                        <span style={{ color: p.cumulative >= 0 ? theme.colors.up : theme.colors.down }}>
                          {p.cumulative >= 0 ? '+' : ''}${p.cumulative.toFixed(2)}
                        </span>
                      </div>
                    </div>
                  )
                }}
              />
            </AreaChart>
          </ResponsiveContainer>
            )
          })()}
        </div>
      )
    })()}

    {/* Closed trades — Day-32 editorial section */}
    <section className="space-y-0">
      <div className="flex items-baseline gap-3 pb-3" style={{ borderBottom: `1px solid ${theme.colors.border}` }}>
        <h2
          className="text-xl"
          style={{ color: theme.colors.text, fontWeight: 500 }}
        >
          Closed trades
        </h2>
        <span
          className="text-xs tabular-nums"
          style={{ color: theme.colors.textHint, fontFamily: 'var(--font-mono)' }}
        >
          {String(brain.closed_count).padStart(2, '0')}
        </span>
      </div>

      {brainClosed.length === 0 ? (
        <p className="text-[11px]" style={{ color: theme.colors.textHint }}>
          No closed trades yet. Trades close when they hit their target, stop loss, expire after 30 days, or the brain signals SELL.
        </p>
      ) : (
        <div className="divide-y" style={{ borderColor: theme.colors.border }}>
          {brainClosed.slice(0, closedVisibleCount).map((rc, i) => {
            const daysHeld = rc.entry_date && rc.exit_date
              ? Math.max(1, Math.round((new Date(rc.exit_date).getTime() - new Date(rc.entry_date).getTime()) / 86400000))
              : null
            // Day 26: per-row expansion key. exit_date is the
            // discriminator when the same ticker has closed multiple
            // times (e.g., BTDR on Apr 30 + May 4).
            const rowKey = `${rc.symbol}-${rc.exit_date ?? i}`
            const isExpanded = expandedClosedKey === rowKey
            const hasReasoning = !!(rc.entry_thesis || rc.thesis_last_reason)
            return (
              <div key={rowKey}>
                <button
                  type="button"
                  onClick={() => setExpandedClosedKey(isExpanded ? null : rowKey)}
                  aria-expanded={isExpanded}
                  aria-label={isExpanded ? `Collapse ${rc.symbol} details` : `Expand ${rc.symbol} details`}
                  className="w-full text-left flex items-start justify-between py-4 px-3 transition-opacity hover:opacity-80"
                >
                  <div className="flex flex-col gap-1 min-w-0">
                    <div className="flex items-center gap-2">
                      {rc.is_win
                        ? <TrendingUp size={14} style={{ color: theme.colors.up }} />
                        : <TrendingDown size={14} style={{ color: theme.colors.down }} />
                      }
                      <span
                        className="text-base font-medium"
                        style={{ color: theme.colors.text, fontWeight: 500, letterSpacing: '0.01em' }}
                      >
                        {rc.symbol}
                      </span>
                      {rc.direction === 'SHORT' && (
                        <span
                          className="text-[8px] font-bold uppercase px-1.5 py-0.5 rounded"
                          style={{ backgroundColor: theme.colors.down + '18', color: theme.colors.down }}
                        >
                          ▼ {t.brainPerf.shortSell ?? 'Short'}
                        </span>
                      )}
                      <ExitReasonBadge reason={rc.exit_reason} theme={theme} />
                      {!rc.is_wallet_trade && (
                        <span
                          className="text-[8px] font-medium px-1.5 py-0.5 rounded"
                          style={{ backgroundColor: theme.colors.border + '50', color: theme.colors.textHint }}
                          title={t.wallet?.legacyTooltip ?? 'Pre-wallet legacy trade — P&L shown per-share'}
                        >
                          {t.wallet?.legacyBadge ?? 'Legacy 1-share'}
                        </span>
                      )}
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
                      {hasReasoning && (
                        <span aria-hidden className="text-[10px] ml-auto" style={{ color: theme.colors.textHint }}>
                          {isExpanded ? '▾' : '▸'}
                        </span>
                      )}
                    </div>
                    <div className="text-[10px] tabular-nums pl-[22px]" style={{ color: theme.colors.textHint }}>
                      {rc.is_wallet_trade && rc.position_size_usd != null && (
                        <span style={{ color: theme.colors.textSub }}>${rc.position_size_usd.toFixed(0)} · </span>
                      )}
                      {fmtShortDate(rc.entry_date)} {formatPrice(rc.entry_price)} → {fmtShortDate(rc.exit_date)} {formatPrice(rc.exit_price)}
                      {rc.peak_price != null && (
                        <span style={{ color: theme.colors.textSub }}> (peak {formatPrice(rc.peak_price)})</span>
                      )}
                    </div>
                    {rc.exit_context && (
                      <div className="text-[9px] pl-[22px] mt-0.5" style={{ color: theme.colors.textSub }}>
                        {rc.exit_context}
                      </div>
                    )}
                  </div>
                  <div className="flex flex-col items-end shrink-0">
                    <span className="text-[13px] font-bold tabular-nums" style={{ color: rc.is_win ? theme.colors.up : theme.colors.down }}>
                      {rc.pnl_pct >= 0 ? '+' : ''}{formatPct(rc.pnl_pct)}%
                    </span>
                    {rc.is_wallet_trade && rc.pnl_amount != null && (
                      <span className="text-[10px] font-medium tabular-nums" style={{ color: rc.is_win ? theme.colors.up : theme.colors.down }}>
                        {rc.pnl_amount >= 0 ? '+' : '-'}${Math.abs(rc.pnl_amount).toFixed(2)}
                      </span>
                    )}
                  </div>
                </button>
                {isExpanded && hasReasoning && (
                  <div className="px-3 pb-4 pl-[34px] -mt-2 space-y-3" style={{ color: theme.colors.textSub }}>
                    {rc.entry_thesis && (
                      <div>
                        <div className="text-[9px] uppercase tracking-wide font-semibold mb-1" style={{ color: theme.colors.textHint }}>
                          Why bought · entry score {rc.entry_score ?? '—'}
                        </div>
                        <div className="text-[11px] leading-relaxed" style={{ color: theme.colors.text }}>
                          {rc.entry_thesis}
                        </div>
                      </div>
                    )}
                    {rc.thesis_last_reason && (
                      <div>
                        <div className="text-[9px] uppercase tracking-wide font-semibold mb-1" style={{ color: theme.colors.textHint }}>
                          Why closed · {rc.exit_reason ?? '—'} · exit score {rc.exit_score ?? '—'}
                        </div>
                        <div className="text-[11px] leading-relaxed" style={{ color: theme.colors.text }}>
                          {rc.thesis_last_reason}
                        </div>
                      </div>
                    )}
                    <div className="pt-1">
                      <Link
                        href={`/signals/${rc.symbol}`}
                        className="text-[10px] font-medium hover:underline"
                        style={{ color: theme.colors.primary }}
                      >
                        View {rc.symbol} signal page →
                      </Link>
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
      {brainClosed.length > closedVisibleCount && (
        <button
          onClick={() => setClosedVisibleCount(c => c + 5)}
          className="w-full mt-4 text-[11px] py-2 transition-opacity hover:opacity-80"
          style={{
            backgroundColor: 'transparent',
            color: theme.colors.primary,
            borderTop: `1px solid ${theme.colors.border}`,
            fontFamily: 'var(--font-mono)',
            textTransform: 'uppercase',
            letterSpacing: '0.12em',
          }}
        >
          {t.brainPerf.loadMore ?? 'LOAD MORE'} ↓
        </button>
      )}
    </section>

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
        <div className="grid grid-cols-6 gap-1 pb-2 mb-1" style={{ borderBottom: `1px solid ${theme.colors.border}` }}>
          <p className="text-[9px] font-semibold uppercase tracking-wide" style={{ color: theme.colors.textHint }}>{t.brainPerf.scoreRange}</p>
          <p className="text-[9px] font-semibold uppercase tracking-wide text-center" style={{ color: theme.colors.textHint }}>W / L</p>
          <p className="text-[9px] font-semibold uppercase tracking-wide text-center" style={{ color: theme.colors.textHint }}>{t.stats?.winRate ?? 'Win Rate'}</p>
          <p className="text-[9px] font-semibold uppercase tracking-wide text-center" style={{ color: theme.colors.textHint }}>{t.brainPerf.avgReturn}</p>
          <p className="text-[9px] font-semibold uppercase tracking-wide text-center" style={{ color: theme.colors.textHint }}>Best</p>
          <p className="text-[9px] font-semibold uppercase tracking-wide text-right" style={{ color: theme.colors.textHint }}>Total</p>
        </div>

        {/* Table rows */}
        <div className="space-y-0.5">
          {trackRecord.ranges.map((row) => {
            const r = row as unknown as Record<string, number | string>
            const trades = (r.trades as number) || 0
            const winRate = (r.win_rate as number) || 0
            const avgRet = (r.avg_return_pct as number) || 0
            const best = (r.best as number) || 0
            const worst = (r.worst as number) || 0
            const totalPnl = (r.total_pnl as number) || 0
            const wins = (r.wins as number) || 0
            const losses = (r.losses as number) || 0

            return (
              <div
                key={r.score_range as string}
                className="grid grid-cols-6 gap-1 py-2 rounded-lg px-1"
                style={{ backgroundColor: trades > 0 ? theme.colors.surfaceAlt : 'transparent' }}
              >
                <p className="text-[11px] font-semibold tabular-nums" style={{ color: theme.colors.text }}>{r.score_range}</p>
                <p className="text-[11px] tabular-nums text-center" style={{ color: theme.colors.textSub }}>
                  {trades === 0 ? '\u2014' : (
                    <><span style={{ color: theme.colors.up }}>{wins}</span> / <span style={{ color: theme.colors.down }}>{losses}</span></>
                  )}
                </p>
                <p className="text-[11px] font-semibold tabular-nums text-center" style={{
                  color: trades === 0 ? theme.colors.textHint : winRate >= 60 ? theme.colors.up : winRate >= 50 ? theme.colors.warning : theme.colors.down,
                }}>
                  {trades === 0 ? '\u2014' : `${winRate.toFixed(0)}%`}
                </p>
                <p className="text-[11px] tabular-nums text-center" style={{
                  color: trades === 0 ? theme.colors.textHint : avgRet >= 0 ? theme.colors.up : theme.colors.down,
                }}>
                  {trades === 0 ? '\u2014' : `${avgRet >= 0 ? '+' : ''}${formatPct(avgRet)}%`}
                </p>
                <p className="text-[10px] tabular-nums text-center" style={{ color: theme.colors.textHint }}>
                  {trades === 0 ? '\u2014' : (
                    <><span style={{ color: theme.colors.up }}>{formatPct(best)}%</span> / <span style={{ color: theme.colors.down }}>{formatPct(worst)}%</span></>
                  )}
                </p>
                <p className="text-[11px] font-semibold tabular-nums text-right" style={{
                  color: trades === 0 ? theme.colors.textHint : totalPnl >= 0 ? theme.colors.up : theme.colors.down,
                }}>
                  {trades === 0 ? '\u2014' : `${totalPnl >= 0 ? '+' : ''}${formatPct(totalPnl)}%`}
                </p>
              </div>
            )
          })}
        </div>

        {/* Overall summary */}
        <div className="grid grid-cols-6 gap-1 pt-2 mt-1 px-1" style={{ borderTop: `1px solid ${theme.colors.border}` }}>
          <p className="text-[11px] font-bold" style={{ color: theme.colors.text }}>{t.brainPerf.overall}</p>
          <p className="text-[11px] font-bold tabular-nums text-center" style={{ color: theme.colors.text }}>{trackRecord.total_trades}</p>
          <p className="text-[11px] font-bold tabular-nums text-center" style={{
            color: trackRecord.overall_win_rate >= 60 ? theme.colors.up : trackRecord.overall_win_rate >= 50 ? theme.colors.warning : theme.colors.down,
          }}>
            {trackRecord.overall_win_rate.toFixed(0)}%
          </p>
          <p className="text-[11px] text-center" style={{ color: theme.colors.textHint }}></p>
          <p className="text-[11px] text-center" style={{ color: theme.colors.textHint }}></p>
          <p className="text-[11px] text-right" style={{ color: theme.colors.textHint }}></p>
        </div>
      </Card>
    )}
    </div>
  )
}
