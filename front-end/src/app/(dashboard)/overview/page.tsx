'use client'

import { useState, useMemo } from 'react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useAllSignals } from '@/hooks/useSignals'
import { useStats } from '@/hooks/useStats'
import { StatsBar } from '@/components/dashboard/StatsBar'
import { QuickActions } from '@/components/dashboard/QuickActions'
import { BudgetWidget, AlertsWidget, PortfolioWidget, BrainPerformanceWidget } from '@/components/dashboard/DashboardWidgets'
import { SignalList } from '@/components/signals/SignalList'
import { WatchlistTable } from '@/components/watchlist/WatchlistTable'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { Clock } from 'lucide-react'
import type { Signal } from '@/types/signal'

type BucketFilter = 'ALL' | 'HIGH_RISK' | 'SAFE_INCOME'

function isMarketOpen(): boolean {
  const now = new Date()
  const et = new Date(now.toLocaleString('en-US', { timeZone: 'America/New_York' }))
  const day = et.getDay()
  if (day === 0 || day === 6) return false
  const minutes = et.getHours() * 60 + et.getMinutes()
  return minutes >= 570 && minutes < 960 // 9:30 AM - 4:00 PM
}

function isWeekday(): boolean {
  const now = new Date()
  const et = new Date(now.toLocaleString('en-US', { timeZone: 'America/New_York' }))
  const day = et.getDay()
  return day !== 0 && day !== 6
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function formatNextScan(nextScanTime: string | null, t: Record<string, any>): string | null {
  if (!nextScanTime) return null
  const scanDate = new Date(nextScanTime)
  const now = new Date()
  const diffMs = scanDate.getTime() - now.getTime()
  const diffMin = Math.round(diffMs / 60000)
  if (diffMin > 0 && diffMin <= 120) {
    return t.market.nextScanIn.replace('{minutes}', String(diffMin))
  }
  const timeStr = scanDate.toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    timeZone: 'America/New_York',
    timeZoneName: 'short',
  })
  return t.market.nextScanAt.replace('{time}', timeStr)
}

export default function OverviewPage() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const { data: allSignals, isLoading, isError, error } = useAllSignals({ limit: 200 })
  const { data: stats } = useStats()
  const [filter, setFilter] = useState<BucketFilter>('ALL')

  const getGreeting = (): string => {
    const hour = new Date().getHours()
    if (hour < 12) return t.overview.morning
    if (hour < 18) return t.overview.afternoon
    return t.overview.evening
  }

  const marketOpen = isMarketOpen()
  const marketRegime = allSignals?.[0]?.market_regime ?? null
  const nextScanLabel = formatNextScan(stats?.next_scan_time ?? null, t)

  const regimeColors = useMemo<Record<string, string>>(() => ({
    TRENDING: theme.colors.up,
    VOLATILE: theme.colors.warning,
    CRISIS: theme.colors.down,
  }), [theme.colors.up, theme.colors.warning, theme.colors.down])

  const regimeLabels = useMemo<Record<string, string>>(() => ({
    TRENDING: t.market.trending,
    VOLATILE: t.market.volatile,
    CRISIS: t.market.crisis,
  }), [t.market.trending, t.market.volatile, t.market.crisis])

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
      {/* Greeting + Regime badge */}
      <div>
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold" style={{ color: theme.colors.text }}>
            {getGreeting()}
          </h1>
          {marketRegime && (
            <span
              className="text-[10px] font-bold px-2 py-0.5 rounded-full"
              style={{
                backgroundColor: (regimeColors[marketRegime] || theme.colors.textSub) + '18',
                color: regimeColors[marketRegime] || theme.colors.textSub,
              }}
            >
              {regimeLabels[marketRegime] || marketRegime}
            </span>
          )}
        </div>
        <p className="text-sm mt-1" style={{ color: theme.colors.textSub }}>
          {t.overview.subtitle}
        </p>
      </div>

      {/* Market Status Banner */}
      <Card>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <span
                className="w-2 h-2 rounded-full"
                style={{
                  backgroundColor: marketOpen ? theme.colors.up : theme.colors.textHint,
                  boxShadow: marketOpen ? `0 0 6px ${theme.colors.up}80` : 'none',
                }}
              />
              <span className="text-xs font-medium" style={{ color: theme.colors.text }}>
                {marketOpen ? t.market.open : t.market.closed}
              </span>
            </div>
          </div>
          {nextScanLabel && isWeekday() && (
            <div className="flex items-center gap-1.5">
              <Clock size={12} style={{ color: theme.colors.textSub }} />
              <span className="text-[11px]" style={{ color: theme.colors.textSub }}>
                {nextScanLabel}
              </span>
            </div>
          )}
        </div>
      </Card>

      {/* Stats */}
      <StatsBar />

      {/* Safe to Buy / Must Sell -- hero section */}
      <QuickActions />

      {/* Brain Performance — full width */}
      <BrainPerformanceWidget />

      {/* Dashboard Widgets: Budget + Alerts + Portfolio */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 items-stretch">
        <BudgetWidget />
        <AlertsWidget />
        <PortfolioWidget />
      </div>

      {/* Watchlist — compact horizontal */}
      <Card>
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: theme.colors.textSub }}>
            {t.overview.watchlist}
          </h2>
        </div>
        <WatchlistTable signals={allSignals} compact />
      </Card>

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
  )
}
