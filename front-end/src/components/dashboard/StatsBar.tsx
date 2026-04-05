'use client'

import { useTheme } from '@/hooks/useTheme'
import { useStats } from '@/hooks/useStats'
import { useI18nStore } from '@/store/i18nStore'
import { StatCard } from '@/components/ui/StatCard'
import { Skeleton } from '@/components/ui/Skeleton'

export function StatsBar() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const { data: stats, isLoading } = useStats()

  if (isLoading) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} width="100%" height={100} borderRadius={14} />
        ))}
      </div>
    )
  }

  if (!stats) return null

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      <StatCard
        label={t.stats.gems}
        value={stats.gems_today}
        sub={t.stats.yesterday.replace('{count}', String(stats.gems_yesterday))}
        valueColor={theme.colors.primary}
      />
      <StatCard
        label={t.stats.winRate}
        value={stats.win_rate_30d === 0 ? t.stats.noData : `${(stats.win_rate_30d * 100).toFixed(0)}%`}
        sub={t.stats.thirtyDay}
        valueColor={stats.win_rate_30d === 0 ? theme.colors.textSub : theme.colors.up}
      />
      <StatCard
        label={t.stats.scanned}
        value={stats.tickers_scanned}
        sub={t.stats.tickersToday}
      />
      <StatCard
        label={t.stats.aiCost}
        value={`$${stats.ai_cost_today.toFixed(2)}`}
        sub={t.stats.today}
        valueColor={theme.colors.warning}
      />
    </div>
  )
}
