'use client'

import { useTheme } from '@/hooks/useTheme'
import { useStats } from '@/hooks/useStats'
import { StatCard } from '@/components/ui/StatCard'
import { Skeleton } from '@/components/ui/Skeleton'

export function StatsBar() {
  const theme = useTheme()
  const { data: stats, isLoading } = useStats()

  if (isLoading) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} width="100%" height={80} borderRadius={14} />
        ))}
      </div>
    )
  }

  if (!stats) return null

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      <StatCard
        label="Gems"
        value={stats.gems_today}
        sub={`Yesterday: ${stats.gems_yesterday}`}
        valueColor={theme.colors.primary}
      />
      <StatCard
        label="Win Rate"
        value={`${(stats.win_rate_30d * 100).toFixed(0)}%`}
        sub="30-day"
        valueColor={theme.colors.up}
      />
      <StatCard
        label="Scanned"
        value={stats.tickers_scanned}
        sub="Tickers today"
      />
      <StatCard
        label="AI Cost"
        value={`$${stats.ai_cost_today.toFixed(2)}`}
        sub="Today"
        valueColor={theme.colors.warning}
      />
    </div>
  )
}
