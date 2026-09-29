'use client'

import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { usePerformanceInsights, useBacktestInsights } from '@/hooks/useInsights'
import { fill } from '@/lib/insights'
import { Skeleton } from '@/components/ui/Skeleton'
import { Button } from '@/components/ui/Button'
import { VerdictBanner } from '@/components/performance/VerdictBanner'
import { EquityChart } from '@/components/performance/EquityChart'
import { CohortsCard, CalibrationCard, OpusCard, SkipRulesCard } from '@/components/performance/OutcomeCards'
import { BacktestSection } from '@/components/performance/BacktestSection'

export default function PerformancePage() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const p = t.performance
  const { data, isLoading, isError, refetch } = usePerformanceInsights()
  const { data: backtest, isLoading: btLoading } = useBacktestInsights()

  return (
    <div className="flex flex-col gap-4 md:gap-6">
      <header className="flex flex-col gap-2">
        <h1 className="text-[26px] md:text-[30px] font-semibold tracking-tight" style={{ color: theme.colors.text }}>{p.title}</h1>
        <p className="text-sm leading-relaxed max-w-[820px]" style={{ color: theme.colors.textSub }}>
          {fill(p.intro, { n: data?.threshold ?? 30 })}
        </p>
      </header>

      {isLoading ? (
        <div className="flex flex-col gap-4">
          <Skeleton height={96} borderRadius={16} />
          <Skeleton height={280} borderRadius={16} />
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} height={220} borderRadius={16} />)}
          </div>
        </div>
      ) : isError || !data ? (
        <div className="rounded-2xl p-6 flex items-center justify-between gap-4" style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.border}` }} role="alert">
          <p className="text-sm" style={{ color: theme.colors.text }}>{p.loadFailed}</p>
          <Button variant="secondary" onClick={() => refetch()}>{t.today.retry}</Button>
        </div>
      ) : (
        <>
          <VerdictBanner data={data} />
          <EquityChart curve={data.equity_curve} />
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 md:gap-5 items-start">
            <CohortsCard data={data} />
            <CalibrationCard data={data} />
            <OpusCard data={data} />
            <SkipRulesCard data={data} />
          </div>
        </>
      )}

      {btLoading ? <Skeleton height={260} borderRadius={16} /> : backtest ? <BacktestSection data={backtest} /> : null}
    </div>
  )
}
