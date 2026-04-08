'use client'

import { useTheme } from '@/hooks/useTheme'
import { useStats } from '@/hooks/useStats'
import { useI18nStore } from '@/store/i18nStore'
import { StatCard } from '@/components/ui/StatCard'
import { Skeleton } from '@/components/ui/Skeleton'
import { interpolate } from '@/lib/utils'

export function StatsBar() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const { data: stats, isLoading } = useStats()

  if (isLoading) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} width="100%" height={100} borderRadius={14} />
        ))}
      </div>
    )
  }

  if (!stats) return null

  return (
    <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
      <StatCard
        label={t.stats.gems}
        value={stats.gems_today}
        sub={interpolate(t.stats.yesterday, { count: stats.gems_yesterday })}
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
        sub={stats.discovered_today > 0
          ? `${stats.discovered_today} discovered`
          : t.stats.tickersToday}
      />
      <StatCard
        label={t.stats.aiCost}
        value={`$${stats.ai_cost_today.toFixed(2)}`}
        sub={t.stats.today}
        valueColor={theme.colors.warning}
      />
      <StatCard
        label={t.stats.fearGreed}
        value={stats.fear_greed ? `${stats.fear_greed.score.toFixed(0)}` : t.stats.noData}
        sub={stats.fear_greed?.label ?? t.stats.noData}
        valueColor={
          !stats.fear_greed ? theme.colors.textSub
          : stats.fear_greed.score <= 25 ? theme.colors.down
          : stats.fear_greed.score <= 45 ? theme.colors.warning
          : stats.fear_greed.score >= 55 ? theme.colors.up
          : theme.colors.textSub
        }
      />
    </div>
  )
}
