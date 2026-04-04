'use client'

import { useState } from 'react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useGemSignals } from '@/hooks/useSignals'
import { StatsBar } from '@/components/dashboard/StatsBar'
import { QuickActions } from '@/components/dashboard/QuickActions'
import { AllocationChart } from '@/components/charts/AllocationChart'
import { SignalList } from '@/components/signals/SignalList'
import { WatchlistTable } from '@/components/watchlist/WatchlistTable'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import type { Signal } from '@/types/signal'

type BucketFilter = 'ALL' | 'HIGH_RISK' | 'SAFE_INCOME'

export default function OverviewPage() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const { data: gems, isLoading, isError, error } = useGemSignals()
  const [filter, setFilter] = useState<BucketFilter>('ALL')

  const getGreeting = (): string => {
    const hour = new Date().getHours()
    if (hour < 12) return t.overview.morning
    if (hour < 18) return t.overview.afternoon
    return t.overview.evening
  }

  const filtered = gems?.filter((s: Signal) => {
    if (filter === 'ALL') return true
    return s.bucket === filter
  })

  const safeCount = gems?.filter((s) => s.bucket === 'SAFE_INCOME').length ?? 0
  const riskCount = gems?.filter((s) => s.bucket === 'HIGH_RISK').length ?? 0

  const filters: { label: string; value: BucketFilter }[] = [
    { label: t.overview.all, value: 'ALL' },
    { label: t.overview.highRisk, value: 'HIGH_RISK' },
    { label: t.overview.safeIncome, value: 'SAFE_INCOME' },
  ]

  return (
    <div className="space-y-8">
      {/* Greeting */}
      <div>
        <h1 className="text-2xl font-bold" style={{ color: theme.colors.text }}>
          {getGreeting()}
        </h1>
        <p className="text-sm mt-1" style={{ color: theme.colors.textSub }}>
          {t.overview.subtitle}
        </p>
      </div>

      {/* Stats */}
      <StatsBar />

      {/* Safe to Buy / Must Sell */}
      <QuickActions />

      {/* Two-column: Allocation + Watchlist */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <AllocationChart
          safeCount={safeCount}
          riskCount={riskCount}
          isLoading={isLoading}
        />
        <Card>
          <h2 className="text-[11px] font-semibold uppercase tracking-wide mb-3" style={{ color: theme.colors.textSub }}>
            {t.overview.watchlist}
          </h2>
          <WatchlistTable />
        </Card>
      </div>

      {/* Gems section */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-bold" style={{ color: theme.colors.text }}>
              {t.overview.topSignals}
            </h2>
            {gems && <Badge variant="gem">{gems.length}</Badge>}
          </div>
        </div>

        {/* Filter tabs */}
        <div
          className="inline-flex items-center gap-1 rounded-xl px-1 py-1 mb-4"
          style={{ backgroundColor: theme.colors.nav }}
        >
          {filters.map((f) => (
            <button
              key={f.value}
              onClick={() => setFilter(f.value)}
              className="px-3 py-1 rounded-lg text-xs font-medium transition-all"
              style={{
                backgroundColor: filter === f.value ? theme.colors.navActive : 'transparent',
                color: filter === f.value ? theme.colors.text : theme.colors.textSub,
                boxShadow: filter === f.value ? (theme.isDark ? '0 1px 3px rgba(0,0,0,0.3)' : '0 1px 3px rgba(0,0,0,0.08)') : 'none',
              }}
            >
              {f.label}
            </button>
          ))}
        </div>

        <SignalList
          signals={filtered}
          isLoading={isLoading}
          isError={isError}
          error={error}
        />
      </div>
    </div>
  )
}
