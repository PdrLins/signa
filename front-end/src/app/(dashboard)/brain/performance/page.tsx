'use client'

import { useQuery } from '@tanstack/react-query'
import Link from 'next/link'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { client } from '@/lib/api'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { Skeleton } from '@/components/ui/Skeleton'
import { PageHeader } from '@/components/layout/PageHeader'
import { Sidebar } from '@/components/layout/Sidebar'
import { TrendingUp, TrendingDown } from 'lucide-react'

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

interface VirtualTrade {
  symbol: string
  entry_price: number
  entry_score: number
  bucket: string
  source: string
}

interface ClosedTrade {
  symbol: string
  pnl_pct: number
  is_win: boolean
  source: string
}

interface VirtualSummary extends TrackStats {
  open_trades: VirtualTrade[]
  recent_closed: ClosedTrade[]
  watchlist: TrackStats
  brain: TrackStats
}

function StatBlock({ label, value, color }: { label: string; value: string; color: string }) {
  const theme = useTheme()
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wide" style={{ color: theme.colors.textHint }}>{label}</p>
      <p className="text-xl font-bold tabular-nums" style={{ color }}>{value}</p>
    </div>
  )
}

function TrackCard({ title, stats, color, trades }: { title: string; stats: TrackStats; color: string; trades: VirtualTrade[] }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t).brainPerf
  const hasClosedData = stats.closed_count > 0

  return (
    <Card>
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-bold" style={{ color: theme.colors.text }}>{title}</h3>
        {hasClosedData && (
          <span className="text-sm font-bold tabular-nums" style={{ color: stats.total_return_pct >= 0 ? theme.colors.up : theme.colors.down }}>
            {stats.total_return_pct >= 0 ? '+' : ''}{stats.total_return_pct.toFixed(1)}%
          </span>
        )}
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-4 gap-4 mb-4">
        <StatBlock
          label={t.openPositions}
          value={String(stats.open_count)}
          color={theme.colors.text}
        />
        <StatBlock
          label={t.closedTrades}
          value={String(stats.closed_count)}
          color={theme.colors.text}
        />
        <StatBlock
          label="Win Rate"
          value={hasClosedData ? `${stats.win_rate.toFixed(0)}%` : '\u2014'}
          color={hasClosedData ? (stats.win_rate >= 60 ? theme.colors.up : stats.win_rate >= 50 ? theme.colors.warning : theme.colors.down) : theme.colors.textSub}
        />
        <StatBlock
          label={t.totalReturn}
          value={hasClosedData ? `${stats.avg_return_pct >= 0 ? '+' : ''}${stats.avg_return_pct.toFixed(1)}%` : '\u2014'}
          color={hasClosedData ? (stats.avg_return_pct >= 0 ? theme.colors.up : theme.colors.down) : theme.colors.textSub}
        />
      </div>

      {/* Win/loss bar */}
      {hasClosedData && (
        <div className="flex items-center gap-1 mb-4">
          <div className="h-2.5 rounded-l-full" style={{ width: `${Math.max(5, stats.win_rate)}%`, backgroundColor: theme.colors.up }} />
          <div className="h-2.5 rounded-r-full" style={{ width: `${Math.max(5, 100 - stats.win_rate)}%`, backgroundColor: theme.colors.down }} />
        </div>
      )}

      {/* Best / Worst */}
      {hasClosedData && (stats.best_trade || stats.worst_trade) && (
        <div className="flex gap-4 mb-4">
          {stats.best_trade && (
            <div className="flex items-center gap-1.5">
              <TrendingUp size={14} style={{ color: theme.colors.up }} />
              <span className="text-[11px] font-semibold" style={{ color: theme.colors.text }}>{stats.best_trade.symbol}</span>
              <span className="text-[11px] font-bold tabular-nums" style={{ color: theme.colors.up }}>+{stats.best_trade.pnl_pct.toFixed(1)}%</span>
            </div>
          )}
          {stats.worst_trade && (
            <div className="flex items-center gap-1.5">
              <TrendingDown size={14} style={{ color: theme.colors.down }} />
              <span className="text-[11px] font-semibold" style={{ color: theme.colors.text }}>{stats.worst_trade.symbol}</span>
              <span className="text-[11px] font-bold tabular-nums" style={{ color: theme.colors.down }}>{stats.worst_trade.pnl_pct.toFixed(1)}%</span>
            </div>
          )}
        </div>
      )}

      {/* Open positions */}
      {trades.length > 0 && (
        <div>
          <p className="text-[10px] uppercase tracking-wide mb-2" style={{ color: theme.colors.textHint }}>
            {t.currentHolding} ({trades.length})
          </p>
          <div className="space-y-1.5">
            {trades.map((vt) => (
              <Link key={vt.symbol} href={`/signals/${vt.symbol}`}>
                <div className="flex items-center justify-between py-1.5 rounded-lg px-2 transition-opacity hover:opacity-80" style={{ backgroundColor: theme.colors.surfaceAlt }}>
                  <div className="flex items-center gap-2">
                    <span className="text-[12px] font-semibold" style={{ color: theme.colors.text }}>{vt.symbol}</span>
                    <Badge variant={vt.bucket === 'SAFE_INCOME' ? 'safe' : 'risk'}>
                      {vt.bucket === 'SAFE_INCOME' ? 'Safe' : 'Risk'}
                    </Badge>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-[11px] tabular-nums" style={{ color: theme.colors.textSub }}>
                      ${Number(vt.entry_price).toFixed(2)}
                    </span>
                    <span className="text-[11px] font-semibold tabular-nums" style={{ color }}>
                      {vt.entry_score}
                    </span>
                  </div>
                </div>
              </Link>
            ))}
          </div>
        </div>
      )}

      {!hasClosedData && trades.length === 0 && (
        <p className="text-[11px]" style={{ color: theme.colors.textHint }}>{t.noTradesYet}</p>
      )}
    </Card>
  )
}

export default function BrainPerformancePage() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t).brainPerf

  const { data, isLoading } = useQuery<VirtualSummary>({
    queryKey: ['stats', 'virtual-portfolio'],
    queryFn: async () => (await client.get<VirtualSummary>('/stats/virtual-portfolio')).data,
    staleTime: 30_000,
  })

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton width={200} height={28} />
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Skeleton width="100%" height={300} borderRadius={14} />
          <Skeleton width="100%" height={300} borderRadius={14} />
        </div>
      </div>
    )
  }

  const watchlistTrades = data?.open_trades.filter(t => t.source === 'watchlist') ?? []
  const brainTrades = data?.open_trades.filter(t => t.source === 'brain') ?? []

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold" style={{ color: theme.colors.text }}>{t.performanceTitle}</h1>
        <p className="text-sm mt-1" style={{ color: theme.colors.textSub }}>{t.performanceSubtitle}</p>
      </div>

      {/* Content + Sidebar grid */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_300px] gap-6 items-start">
        <div className="space-y-6">

      {/* Combined stats */}
      {data && data.closed_count > 0 && (
        <Card>
          <div className="grid grid-cols-3 gap-6">
            <StatBlock
              label="Win Rate"
              value={`${data.win_rate.toFixed(0)}%`}
              color={data.win_rate >= 60 ? theme.colors.up : data.win_rate >= 50 ? theme.colors.warning : theme.colors.down}
            />
            <StatBlock
              label={t.totalReturn}
              value={`${data.total_return_pct >= 0 ? '+' : ''}${data.total_return_pct.toFixed(1)}%`}
              color={data.total_return_pct >= 0 ? theme.colors.up : theme.colors.down}
            />
            <StatBlock
              label={t.closedTrades}
              value={String(data.closed_count)}
              color={theme.colors.text}
            />
          </div>
        </Card>
      )}

      {/* Two tracks side by side */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <TrackCard
          title={t.yourWatchlist}
          stats={data?.watchlist ?? { open_count: 0, closed_count: 0, wins: 0, losses: 0, win_rate: 0, avg_return_pct: 0, total_return_pct: 0, best_trade: null, worst_trade: null }}
          color={theme.colors.primary}
          trades={watchlistTrades}
        />
        <TrackCard
          title={t.brainAutoPicks}
          stats={data?.brain ?? { open_count: 0, closed_count: 0, wins: 0, losses: 0, win_rate: 0, avg_return_pct: 0, total_return_pct: 0, best_trade: null, worst_trade: null }}
          color={theme.colors.warning}
          trades={brainTrades}
        />
      </div>

      {/* Recent closed trades */}
      {data && data.recent_closed.length > 0 && (
        <Card>
          <p className="text-[11px] font-semibold uppercase tracking-wide mb-3" style={{ color: theme.colors.textSub }}>
            {t.closedTrades}
          </p>
          <div className="space-y-1.5">
            {data.recent_closed.map((rc, i) => (
              <Link key={i} href={`/signals/${rc.symbol}`}>
                <div className="flex items-center justify-between py-2 px-2 rounded-lg transition-opacity hover:opacity-80" style={{ backgroundColor: theme.colors.surfaceAlt }}>
                  <div className="flex items-center gap-2">
                    {rc.is_win ? <TrendingUp size={14} style={{ color: theme.colors.up }} /> : <TrendingDown size={14} style={{ color: theme.colors.down }} />}
                    <span className="text-[12px] font-semibold" style={{ color: theme.colors.text }}>{rc.symbol}</span>
                    <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ backgroundColor: (rc.source === 'brain' ? theme.colors.warning : theme.colors.primary) + '12', color: rc.source === 'brain' ? theme.colors.warning : theme.colors.primary }}>
                      {rc.source === 'brain' ? 'Brain' : 'You'}
                    </span>
                  </div>
                  <span className="text-[13px] font-bold tabular-nums" style={{ color: rc.is_win ? theme.colors.up : theme.colors.down }}>
                    {rc.pnl_pct >= 0 ? '+' : ''}{rc.pnl_pct.toFixed(1)}%
                  </span>
                </div>
              </Link>
            ))}
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
