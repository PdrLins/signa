'use client'

import { useState, useMemo } from 'react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useAllSignals } from '@/hooks/useSignals'
import { StatsBar } from '@/components/dashboard/StatsBar'
import { QuickActions } from '@/components/dashboard/QuickActions'
import { BudgetWidget, AlertsWidget, PortfolioWidget, BrainPerformanceWidget, BrainTierBreakdownWidget } from '@/components/dashboard/DashboardWidgets'
import { SignalList } from '@/components/signals/SignalList'
import { WatchlistTable } from '@/components/watchlist/WatchlistTable'
import { ScanSchedule } from '@/components/dashboard/ScanSchedule'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import type { Signal } from '@/types/signal'

type BucketFilter = 'ALL' | 'HIGH_RISK' | 'SAFE_INCOME'


export default function OverviewPage() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const { data: allSignals, isLoading, isError, error } = useAllSignals({ limit: 50 })
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

  return (
    <div className="space-y-6">
      {/* Greeting */}
      <div>
        <h1 className="text-2xl font-bold" style={{ color: theme.colors.text }}>
          {getGreeting()}
        </h1>
        <p className="text-sm mt-1" style={{ color: theme.colors.textSub }}>
          {t.overview.subtitle}
        </p>
      </div>

      {/* Scan Schedule */}
      <ScanSchedule />

      {/* Stats */}
      <StatsBar />

      {/* Safe to Buy / Must Sell -- hero section */}
      <QuickActions />

      {/* Two-column layout: main content left, widgets right */}
      <div className="grid grid-cols-1 lg:grid-cols-[2fr_1fr] gap-4 items-start">
        {/* Left column — wider */}
        <div className="space-y-4">
          <BrainPerformanceWidget />
          <BrainTierBreakdownWidget />

          {/* Top signals */}
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

        {/* Right column — narrower */}
        <div className="space-y-4">
          <BudgetWidget />
          <AlertsWidget />
          <PortfolioWidget />
          <Card>
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: theme.colors.textSub }}>
                {t.overview.watchlist}
              </h2>
            </div>
            <WatchlistTable signals={allSignals} compact />
          </Card>
        </div>
      </div>
    </div>
  )
}
