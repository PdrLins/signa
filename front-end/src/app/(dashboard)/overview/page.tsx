'use client'

import { useState, useMemo } from 'react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useAllSignals } from '@/hooks/useSignals'
import { useStats } from '@/hooks/useStats'
import { QuickActions } from '@/components/dashboard/QuickActions'
import { BudgetWidget, AlertsWidget, PortfolioWidget, BrainPerformanceWidget, BrainTierBreakdownWidget } from '@/components/dashboard/DashboardWidgets'
import { SignalList } from '@/components/signals/SignalList'
import { WatchlistTable } from '@/components/watchlist/WatchlistTable'
import { ScanStatusBar } from '@/components/dashboard/ScanStatusBar'
import { MetricCard } from '@/components/dashboard/MetricCard'
import { FearGreedGauge } from '@/components/dashboard/FearGreedGauge'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { Skeleton } from '@/components/ui/Skeleton'
import type { Signal } from '@/types/signal'

type BucketFilter = 'ALL' | 'HIGH_RISK' | 'SAFE_INCOME'


export default function OverviewPage() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const { data: allSignals, isLoading, isError, error } = useAllSignals({ limit: 50 })
  const { data: stats, isLoading: statsLoading } = useStats()
  const [filter, setFilter] = useState<BucketFilter>('ALL')

  const getGreeting = (): string => {
    const hour = new Date().getHours()
    if (hour < 12) return t.overview.morning
    if (hour < 18) return t.overview.afternoon
    return t.overview.evening
  }

  const topSignals = useMemo(() => {
    return allSignals
      ?.filter((s: Signal) => {
        if (filter === 'ALL') return true
        return s.bucket === filter
      })
      .sort((a, b) => b.score - a.score)
      .slice(0, 10)
  }, [allSignals, filter])

  const { totalCount, buyCount, gemCount } = useMemo(() => ({
    totalCount: allSignals?.length ?? 0,
    buyCount: allSignals?.filter((s) => s.action === 'BUY').length ?? 0,
    gemCount: allSignals?.filter((s) => s.is_gem).length ?? 0,
  }), [allSignals])

  const filters: { label: string; value: BucketFilter }[] = [
    { label: t.overview.all, value: 'ALL' },
    { label: t.overview.highRisk, value: 'HIGH_RISK' },
    { label: t.overview.safeIncome, value: 'SAFE_INCOME' },
  ]

  // Win rate formatting
  const winRateDisplay = stats
    ? stats.win_rate_30d === 0
      ? t.stats?.noData ?? '\u2014'
      : `${(stats.win_rate_30d * 100).toFixed(0)}%`
    : '\u2014'
  const winRateColor = stats
    ? stats.win_rate_30d === 0
      ? theme.colors.textSub
      : theme.colors.up
    : theme.colors.textSub

  return (
    <div className="space-y-4">
      {/* Row 1: Header + Scan Status */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: theme.colors.text }}>
            {getGreeting()}
          </h1>
          <p className="text-sm mt-0.5" style={{ color: theme.colors.textSub }}>
            {t.overview.subtitle}
          </p>
        </div>
        <ScanStatusBar />
      </div>

      {/* Row 2: Key Metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {statsLoading ? (
          <>
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} width="100%" height={90} borderRadius={14} />
            ))}
          </>
        ) : (
          <>
            <MetricCard
              label={t.stats?.gems ?? 'Gems Today'}
              value={stats?.gems_today ?? 0}
              sub={stats ? `${stats.gems_yesterday} ${t.stats?.yesterday?.replace('{count}', '') ?? 'yesterday'}`.trim() : undefined}
              valueColor={theme.colors.primary}
            />
            <MetricCard
              label={t.stats?.winRate ?? 'Win Rate'}
              value={winRateDisplay}
              sub={t.stats?.thirtyDay ?? '30-day'}
              valueColor={winRateColor}
            />
            <MetricCard
              label={t.stats?.scanned ?? 'Scanned'}
              value={stats?.tickers_scanned ?? 0}
              sub={
                stats && stats.discovered_today > 0
                  ? `${stats.discovered_today} discovered`
                  : (t.stats?.tickersToday ?? 'tickers today')
              }
            />
            {/* Fear & Greed Gauge */}
            <MetricCard label="" value="">
              <div suppressHydrationWarning>
                <span
                  className="text-[10px] font-semibold uppercase tracking-wide mb-1 block"
                  style={{ color: theme.colors.textSub }}
                >
                  {t.stats?.fearGreed ?? 'Fear & Greed'}
                </span>
                <FearGreedGauge
                  score={stats?.fear_greed?.score ?? null}
                  label={stats?.fear_greed?.label ?? null}
                />
              </div>
            </MetricCard>
          </>
        )}
      </div>

      {/* Quick Actions — full width (needs the horizontal space for 2-col layout) */}
      <QuickActions />

      {/* Row 3: Main content grid */}
      <div className="grid grid-cols-1 lg:grid-cols-[5fr_2fr] gap-4 items-start">
        {/* Left: primary content */}
        <div className="space-y-4">
          <BrainPerformanceWidget />

          {/* Top Signals */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <h2 className="text-lg font-bold" style={{ color: theme.colors.text }}>
                  {t.overview.topSignals}
                </h2>
                {totalCount > 0 && (
                  <div className="flex items-center gap-1.5">
                    <Badge variant="buy">{buyCount} BUY</Badge>
                    {gemCount > 0 && <Badge variant="gem">{gemCount} GEM</Badge>}
                  </div>
                )}
              </div>
            </div>

            {/* Filter tabs */}
            <div
              className="inline-flex items-center gap-0.5 rounded-lg px-0.5 py-0.5 mb-4"
              style={{ backgroundColor: theme.colors.nav }}
            >
              {filters.map((f) => (
                <button
                  key={f.value}
                  onClick={() => setFilter(f.value)}
                  className="px-2.5 py-1 rounded-md text-[11px] font-medium transition-all"
                  style={{
                    backgroundColor: filter === f.value ? theme.colors.navActive : 'transparent',
                    color: filter === f.value ? theme.colors.text : theme.colors.textSub,
                  }}
                >
                  {f.label}
                </button>
              ))}
            </div>

            <SignalList
              signals={topSignals}
              isLoading={isLoading}
              isError={isError}
              error={error}
            />
          </div>
        </div>

        {/* Right: sidebar widgets */}
        <div className="space-y-4">
          <BrainTierBreakdownWidget />
          <BudgetWidget />
          <Card>
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: theme.colors.textSub }}>
                {t.overview.watchlist}
              </h2>
            </div>
            <WatchlistTable signals={allSignals} compact />
          </Card>
          <AlertsWidget />
          <PortfolioWidget />
        </div>
      </div>
    </div>
  )
}
