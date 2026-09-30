'use client'

import { memo, useId, useMemo, useState } from 'react'
import Link from 'next/link'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useAccess } from '@/hooks/useAccess'
import { useProfileOptions } from '@/hooks/useProfile'
import { useMoney, usePortfolioPerformance } from '@/hooks/usePortfolioInsights'
import { fill, shortDate, signedPct } from '@/lib/insights'
import { pct } from '@/components/holdings/format'
import { SectionCard } from '@/components/profile/ui'
import { ChipGroup, Freshness, PremiumHint, QueryError, SkeletonCards, Stat, isUpgrade, useSignColor } from '@/components/tracker/ui'
import type { Driver, DriverSet, HistoryRange, Scope } from '@/types/tracker'

const RANGES: HistoryRange[] = ['1M', '3M', 'YTD', '1Y', '5Y', 'ALL']

function pts(v: number | null | undefined, unit: string): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—'
  const r = Number(v.toFixed(2))
  return `${r > 0 ? '+' : r < 0 ? '−' : ''}${Math.abs(r).toFixed(2)} ${unit}`
}

const DriverBar = memo(function DriverBar({ d, max, vs }: { d: Driver; max: number; vs: boolean }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const tp = t.insightsPage.performance
  const v = (vs ? d.vs_benchmark_pts : d.contribution_pts) ?? 0
  const color = v >= 0 ? theme.colors.up : theme.colors.down
  const w = max > 0 ? Math.max(2, (Math.abs(v) / max) * 100) : 0
  return (
    <li className="flex flex-col gap-1 min-w-0">
      <div className="flex items-baseline justify-between gap-2 text-[13px]">
        <Link href={`/stocks/${encodeURIComponent(d.symbol)}`} className="font-semibold underline-offset-2 hover:underline truncate"
          style={{ color: theme.colors.text }}>{d.symbol}</Link>
        <span className="tabular-nums shrink-0" style={{ color }}>{pts(v, tp.pts)}</span>
      </div>
      <div className="h-2 rounded-full overflow-hidden" aria-hidden="true" style={{ backgroundColor: theme.colors.surfaceAlt }}>
        <div className="h-full rounded-full" style={{ width: `${w}%`, backgroundColor: color }} />
      </div>
      <p className="text-[11.5px] tabular-nums" style={{ color: theme.colors.textHint }}>
        {fill(tp.driverLine, { weight: pct(d.weight_pct, 1), ret: signedPct(d.return_pct, 1) })}
      </p>
    </li>
  )
})

function Drivers({ set, vs }: { set: DriverSet; vs: boolean }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const tp = t.insightsPage.performance
  const max = useMemo(() => Math.max(0, ...[...set.positive, ...set.negative]
    .map((d) => Math.abs((vs ? d.vs_benchmark_pts : d.contribution_pts) ?? 0))), [set, vs])
  if (set.positive.length === 0 && set.negative.length === 0) {
    return <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{tp.noDrivers}</p>
  }
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-4">
      <div className="flex flex-col gap-2 min-w-0">
        <h3 className="text-[12.5px] font-semibold" style={{ color: theme.colors.textSub }}>{vs ? tp.aheadOfIndex : tp.helped}</h3>
        {set.positive.length === 0 ? <p className="text-[12.5px]" style={{ color: theme.colors.textHint }}>{tp.none}</p>
          : <ul className="flex flex-col gap-3">{set.positive.map((d) => <DriverBar key={d.symbol} d={d} max={max} vs={vs} />)}</ul>}
      </div>
      <div className="flex flex-col gap-2 min-w-0">
        <h3 className="text-[12.5px] font-semibold" style={{ color: theme.colors.textSub }}>{vs ? tp.behindIndex : tp.hurt}</h3>
        {set.negative.length === 0 ? <p className="text-[12.5px]" style={{ color: theme.colors.textHint }}>{tp.none}</p>
          : <ul className="flex flex-col gap-3">{set.negative.map((d) => <DriverBar key={d.symbol} d={d} max={max} vs={vs} />)}</ul>}
      </div>
    </div>
  )
}

/** Insights → Performance: return, gain, dividends, drivers, optional benchmark. */
export function PerformanceTab({ scope }: { scope: Scope }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const tp = t.insightsPage.performance
  const { can } = useAccess()
  const selId = useId()
  const [range, setRange] = useState<HistoryRange>('1Y')
  const [compare, setCompare] = useState('')
  const options = useProfileOptions(can('area.profile'))
  const benchmarks = options.data?.compare_indexes ?? []
  const q = usePortfolioPerformance(scope, range, compare || null)
  const p = q.data && q.data.range === range ? q.data : null
  const { fmt, signed } = useMoney(p?.currency)
  const signColor = useSignColor()
  const rangeOptions = useMemo(() => RANGES.map((r) => ({ value: r, label: (t.trackerUi.ranges as Record<string, string>)[r] ?? r })), [t])
  const cmp = p?.compare ?? null
  const upgrade = !!q.error && isUpgrade(q.error)

  return (
    <div className="flex flex-col gap-4 min-w-0">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <ChipGroup value={range} options={rangeOptions} onChange={setRange} label={t.trackerUi.value.rangeLabel} />
        {benchmarks.length > 0 && (
          <div className="flex items-center gap-2 min-w-0">
            <label htmlFor={selId} className="text-[13px] shrink-0" style={{ color: theme.colors.textSub }}>{tp.compare}</label>
            <select id={selId} value={compare} onChange={(e) => setCompare(e.target.value)}
              className="min-h-[44px] rounded-xl px-3 text-[16px] md:text-[14px] min-w-0 focus-visible:outline focus-visible:outline-2"
              style={{ backgroundColor: theme.colors.surfaceAlt, border: `1px solid ${theme.colors.border}`, color: theme.colors.text, outlineColor: theme.colors.primary }}>
              <option value="">{tp.compareOff}</option>
              {benchmarks.map((b) => <option key={b.symbol} value={b.symbol}>{b.symbol.replace(/\.TO$/, '')} · {b.name}</option>)}
            </select>
          </div>
        )}
      </div>

      {upgrade ? <PremiumHint body={t.trackerUi.value.fullHistory} />
        : !!q.error && !p ? <QueryError error={q.error} onRetry={() => q.refetch()} />
          : !p ? <SkeletonCards heights={[140, 220]} /> : (
            <>
              <SectionCard title={tp.returnTitle}
                subtitle={fill(tp.period, { start: shortDate(p.start, locale, true), end: shortDate(p.end, locale, true) })}>
                {cmp ? (
                  <div className="grid grid-cols-3 gap-2">
                    <Stat label={tp.you} value={signedPct(p.return_pct)} color={signColor(p.return_pct)} />
                    <Stat label={cmp.symbol.replace(/\.TO$/, '')} value={signedPct(cmp.return_pct)} color={signColor(cmp.return_pct)} sub={tp.index} />
                    <Stat label={tp.difference} value={pts(cmp.difference_pts, tp.pts)} color={signColor(cmp.difference_pts)} />
                  </div>
                ) : (
                  <p className="text-[30px] font-bold tabular-nums leading-tight" style={{ color: signColor(p.return_pct) }}>
                    {signedPct(p.return_pct)}
                  </p>
                )}
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                  <Stat label={tp.gain} value={signed(p.gain)} color={signColor(p.gain)} />
                  <Stat label={tp.dividends} value={fmt(p.dividends_received)} />
                  {p.net_flows !== null && <Stat label={tp.netFlows} value={signed(p.net_flows)} />}
                </div>
                <p className="text-[12px]" style={{ color: theme.colors.textHint }}>
                  {p.method === 'transactions'
                    ? (p.flows_basis === 'deposits' ? tp.methodDeposits : tp.methodTrades)
                    : <>{tp.methodEstimate}{' '}
                      <Link href="/profile/transactions" className="underline underline-offset-2 font-medium" style={{ color: theme.colors.primary }}>
                        {t.trackerUi.value.addTransactions}
                      </Link></>}
                </p>
                <Freshness asOf={p.as_of} delayed={p.delayed_minutes} />
              </SectionCard>

              <SectionCard title={cmp ? fill(tp.driversVs, { symbol: cmp.symbol.replace(/\.TO$/, '') }) : tp.driversTitle}
                subtitle={cmp ? tp.driversVsHelp : tp.driversHelp}>
                <Drivers set={cmp ? cmp.drivers : p.drivers} vs={!!cmp} />
              </SectionCard>
            </>
          )}
    </div>
  )
}
