'use client'

import Link from 'next/link'
import { RefreshCw } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useTodayInsights } from '@/hooks/useInsights'
import { useStats } from '@/hooks/useStats'
import { useScanTrigger } from '@/hooks/useScanTrigger'
import { isMarketOpen, DEFAULT_TIMEZONE } from '@/lib/utils'
import { fill, etTime } from '@/lib/insights'
import { Skeleton } from '@/components/ui/Skeleton'
import { Button } from '@/components/ui/Button'
import { ScanProgressPanel } from '@/components/scans/ScanProgressPanel'
import { StatusStrip } from '@/components/today/StatusStrip'
import { ScanFunnel } from '@/components/today/ScanFunnel'
import { DecisionsList } from '@/components/today/DecisionsList'
import { OpenPositionsCard } from '@/components/today/OpenPositionsCard'
import { PortfolioRiskCard } from '@/components/today/PortfolioRiskCard'
import { CheckSearchBox } from '@/components/check/CheckSearchBox'

export default function TodayPage() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const { data, isLoading, isError, refetch } = useTodayInsights()
  const { data: stats } = useStats()
  const { scanning, progress, cooldown, trigger, phaseLabel } = useScanTrigger()
  const tt = t.today

  const dateStr = new Date().toLocaleDateString(locale === 'pt' ? 'pt-BR' : 'en-US', {
    weekday: 'long', month: 'short', day: 'numeric', timeZone: DEFAULT_TIMEZONE,
  })
  const scanTime = data?.scan ? etTime(data.scan.completed_at ?? data.scan.started_at, locale) : null
  const meta = [
    dateStr,
    isMarketOpen() ? (t.market?.open ?? 'Market open') : (t.market?.closed ?? 'Market closed'),
    scanTime ? fill(tt.lastScan, { time: scanTime }) : tt.noScan,
    stats?.next_scan_time ? fill(tt.nextScan, { time: etTime(stats.next_scan_time, locale) }) : null,
  ].filter(Boolean).join(' · ')

  const scanLabel = scanning ? tt.scanning : tt.scanNow

  return (
    <div className="flex flex-col gap-4 md:gap-6">
      <header className="flex items-center md:items-end justify-between gap-4">
        <div className="flex flex-col gap-1.5 min-w-0">
          <h1 className="text-[26px] md:text-[30px] font-semibold tracking-tight" style={{ color: theme.colors.text }}>
            {tt.title}
          </h1>
          <p className="text-[13px] md:text-sm" style={{ color: theme.colors.textSub }}>{meta}</p>
        </div>
        <div className="flex items-center gap-2.5 shrink-0">
          <CheckSearchBox className="hidden lg:flex" />
          <Link
            href="/logs"
            className="hidden md:inline-flex items-center h-11 px-[18px] rounded-[10px] text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
            style={{ border: `1px solid ${theme.colors.border}`, color: theme.colors.text, outlineColor: theme.colors.primary }}
          >
            {tt.scanLog}
          </Link>
          <div className="hidden md:block">
            <Button onClick={trigger} disabled={scanning || cooldown}>
              <span className="flex items-center gap-2">
                <RefreshCw size={16} aria-hidden="true" className={scanning ? 'animate-spin' : ''} />
                {scanLabel}
              </span>
            </Button>
          </div>
          <button
            type="button"
            onClick={trigger}
            disabled={scanning || cooldown}
            aria-label={scanLabel}
            className="md:hidden w-11 h-11 rounded-xl flex items-center justify-center disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
            style={{ backgroundColor: theme.colors.primary, color: theme.colors.surface, outlineColor: theme.colors.primary }}
          >
            <RefreshCw size={18} aria-hidden="true" className={scanning ? 'animate-spin' : ''} />
          </button>
        </div>
      </header>

      <CheckSearchBox className="lg:hidden" />

      {scanning && progress && <ScanProgressPanel progress={progress} phaseLabel={phaseLabel} />}

      {!scanning && data?.running_scan && (
        <div
          role="status"
          className="rounded-2xl px-5 py-4 flex items-center gap-4"
          style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.border}` }}
        >
          <RefreshCw size={18} aria-hidden="true" className="animate-spin shrink-0" style={{ color: theme.colors.primary }} />
          <div className="flex flex-col gap-1 min-w-0">
            <span className="text-sm font-medium" style={{ color: theme.colors.text }}>
              {fill(tt.runningTitle, { pct: data.running_scan.progress_pct ?? 0 })}
              {data.running_scan.phase ? ` · ${phaseLabel(data.running_scan.phase)}` : ''}
            </span>
            <span className="text-[13px]" style={{ color: theme.colors.textSub }}>{tt.runningBody}</span>
          </div>
        </div>
      )}

      {isLoading ? (
        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
            {Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} height={108} borderRadius={14} className={i === 4 ? 'hidden lg:block' : ''} />)}
          </div>
          <Skeleton height={200} borderRadius={16} />
          <Skeleton height={360} borderRadius={16} />
        </div>
      ) : isError || !data ? (
        <div className="rounded-2xl p-6 flex items-center justify-between gap-4" style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.border}` }} role="alert">
          <p className="text-sm" style={{ color: theme.colors.text }}>{tt.loadFailed}</p>
          <Button variant="secondary" onClick={() => refetch()}>{tt.retry}</Button>
        </div>
      ) : (
        <>
          <StatusStrip status={data.status} />
          {data.funnel && <ScanFunnel funnel={data.funnel} scan={data.scan} limits={data.limits} />}
          <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_380px] gap-4 md:gap-5 items-start">
            <DecisionsList decisions={data.decisions} decisionsLogged={data.decisions_logged ?? true} />
            <aside className="flex flex-col gap-4 md:gap-5">
              <OpenPositionsCard positions={data.positions} />
              <PortfolioRiskCard risk={data.risk} limits={data.limits} />
            </aside>
          </div>
        </>
      )}
    </div>
  )
}
