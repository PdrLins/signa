'use client'

import { RefreshCw } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { formatPct } from '@/lib/utils'
import type { TrackStats, VirtualSummary } from './types'

interface PositionsHeroProps {
  data: VirtualSummary | undefined
  brain: TrackStats
  autoRefresh: boolean
  countdown: number
  isFetching: boolean
  onToggleAutoRefresh: () => void
  onRefresh: () => void
}

export function PositionsHero({ data, brain, autoRefresh, countdown, isFetching, onToggleAutoRefresh, onRefresh }: PositionsHeroProps) {
  const theme = useTheme()
    const wallet = data?.wallet
    const portfolioValue = wallet?.total_value
    const roiPct = wallet?.roi_pct ?? 0
    const realized = brain.total_pnl_amount_wallet ?? 0
    return (
      <div className="flex items-start justify-between gap-6 pt-2 pb-6 border-b" style={{ borderColor: theme.colors.border }}>
        <div className="min-w-0 flex-1">
          <p
            className="text-[10px] uppercase tracking-[0.18em] mb-3"
            style={{ color: theme.colors.textHint, fontFamily: 'var(--font-mono)' }}
          >
            BRAIN · {new Date().toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })}
          </p>
          <h1
            className=" font-medium leading-[0.95] tracking-tight mb-3"
            style={{
              color: theme.colors.text,
              fontSize: 'clamp(2rem, 4.5vw, 3.25rem)',
            }}
          >
            {portfolioValue != null ? (
              <>
                <span style={{ color: theme.colors.textSub, fontSize: '0.5em', verticalAlign: 'top', marginRight: '0.1em' }}>$</span>
                <span className="tabular-nums" style={{ fontFamily: 'var(--font-mono)', fontWeight: 500 }}>
                  {portfolioValue.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </span>
              </>
            ) : (
              <span style={{ color: theme.colors.textHint }}>—</span>
            )}
          </h1>
          <p className="text-base leading-relaxed italic" style={{ color: theme.colors.textSub }}>
            {portfolioValue != null && wallet?.initial_deposit ? (
              <>
                <span style={{ color: roiPct >= 0 ? theme.colors.up : theme.colors.down, fontFamily: 'var(--font-mono)', fontStyle: 'normal', fontWeight: 500 }}>
                  {roiPct >= 0 ? '+' : ''}{formatPct(roiPct)}%
                </span>
                {' '}on capital since funding ·{' '}
                <span style={{ fontFamily: 'var(--font-mono)', fontStyle: 'normal', fontWeight: 500, color: realized >= 0 ? theme.colors.up : theme.colors.down }}>
                  {realized >= 0 ? '+' : '-'}${Math.abs(realized).toFixed(2)}
                </span>
                {' '}realized across{' '}
                <span style={{ fontFamily: 'var(--font-mono)', fontStyle: 'normal' }}>{brain.closed_count}</span>
                {' '}closed trades
              </>
            ) : (
              'Tracking begins after first deposit.'
            )}
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={onToggleAutoRefresh}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[10px] font-semibold transition-all"
            style={{
              backgroundColor: autoRefresh ? theme.colors.primary + '15' : 'transparent',
              color: autoRefresh ? theme.colors.primary : theme.colors.textHint,
              border: `1px solid ${autoRefresh ? theme.colors.primary + '30' : theme.colors.border}`,
              fontFamily: 'var(--font-mono)',
            }}
            aria-label="Toggle auto-refresh"
          >
            {autoRefresh ? `${countdown}s` : 'AUTO'}
          </button>
          <button
            onClick={onRefresh}
            disabled={isFetching}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-semibold transition-opacity hover:opacity-80 disabled:opacity-50"
            style={{
              backgroundColor: 'transparent',
              color: theme.colors.textSub,
              border: `1px solid ${theme.colors.border}`,
              fontFamily: 'var(--font-mono)',
            }}
          >
            <RefreshCw size={12} className={isFetching ? 'animate-spin' : ''} />
            {isFetching ? 'REFRESHING' : 'REFRESH'}
          </button>
        </div>
      </div>
    )
}
