'use client'

import { useTheme } from '@/hooks/useTheme'
import { useStats } from '@/hooks/useStats'
import { useI18nStore } from '@/store/i18nStore'
import { StatCard } from '@/components/ui/StatCard'
import { Skeleton } from '@/components/ui/Skeleton'

const SPARK_GEMS = [2, 3, 1, 4, 3, 5, 4, 6, 5, 7]
const SPARK_WIN = [55, 58, 60, 57, 62, 65, 63, 68, 70, 72]
const SPARK_SCANNED = [800, 850, 900, 880, 950, 1000, 980, 1020, 1050, 1100]
const SPARK_COST = [0.12, 0.15, 0.18, 0.14, 0.20, 0.22, 0.19, 0.25, 0.21, 0.18]

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
        sparkData={SPARK_GEMS}
        sparkPositive
      />
      <StatCard
        label={t.stats.winRate}
        value={`${(stats.win_rate_30d * 100).toFixed(0)}%`}
        sub={t.stats.thirtyDay}
        valueColor={theme.colors.up}
        sparkData={SPARK_WIN}
        sparkPositive
      />
      <StatCard
        label={t.stats.scanned}
        value={stats.tickers_scanned}
        sub={t.stats.tickersToday}
        sparkData={SPARK_SCANNED}
        sparkPositive
      />
      <StatCard
        label={t.stats.aiCost}
        value={`$${stats.ai_cost_today.toFixed(2)}`}
        sub={t.stats.today}
        valueColor={theme.colors.warning}
        sparkData={SPARK_COST}
        sparkPositive={false}
      />
    </div>
  )
}
