'use client'

import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import dynamic from 'next/dynamic'
import Link from 'next/link'
import { ChevronDown, Maximize2, X } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useAccess } from '@/hooks/useAccess'
import { useProfileOptions } from '@/hooks/useProfile'
import { useMoney, usePortfolioHistory } from '@/hooks/usePortfolioInsights'
import { etTime, fill, shortDate, signedPct } from '@/lib/insights'
import {
  ChipGroup, Freshness, LiveValue, PremiumHint, QueryError, arrow, isUpgrade, useSignColor,
} from '@/components/tracker/ui'
import type { HistoryRange, PortfolioSummary, Scope } from '@/types/tracker'

const ValueChart = dynamic(() => import('@/components/tracker/ValueChart'), { ssr: false })

const RANGES: HistoryRange[] = ['1D', '1W', '1M', '3M', 'YTD', '1Y', '5Y', 'ALL']
const PREMIUM_RANGES = new Set<HistoryRange>(['5Y', 'ALL'])

/** Big value + range change + total gain + live 1D…All chart with an opt-in
 *  benchmark. Used at the top of /holdings. */
export function PortfolioValueCard({ scope, summary }: { scope: Scope; summary: PortfolioSummary }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const tv = t.trackerUi.value
  const locale = useI18nStore((s) => s.locale)
  const { can } = useAccess()
  const [range, setRange] = useState<HistoryRange>('1D')
  const [compare, setCompare] = useState<string | null>(null)
  const [menuOpen, setMenuOpen] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const menuId = useId()
  const menuRef = useRef<HTMLDivElement>(null)
  const history = usePortfolioHistory(scope, range, compare)
  const options = useProfileOptions(can('area.profile'))
  const benchmarks = useMemo(() => options.data?.compare_indexes ?? [], [options.data])
  const { fmt, signed } = useMoney(summary.currency)
  const signColor = useSignColor()

  const h = history.data && history.data.range === range ? history.data : null
  const series = useMemo(() => h?.series ?? [], [h])

  // Range change: 1D = today's change vs the previous close (summary);
  // other ranges = last − first point of the series.
  const change = useMemo(() => {
    if (range === '1D' && summary.day_change.abs !== null) {
      const prevClose = summary.total !== null ? summary.total - summary.day_change.abs : null
      return { abs: summary.day_change.abs, pct: summary.day_change.pct, base: prevClose }
    }
    if (series.length < 2) return { abs: null, pct: null, base: series[0]?.value ?? null }
    const first = series[0].value
    const last = series[series.length - 1].value
    return { abs: last - first, pct: first ? (last / first - 1) * 100 : h?.range_return_pct ?? null, base: first }
  }, [range, summary, series, h])

  const color = signColor(change.abs)
  const rangeLabel = (t.trackerUi.rangeLong as Record<string, string>)[range] ?? range
  const benchName = h?.compare?.symbol ?? compare
  const compareLabel = benchName ? fill(tv.vs, { symbol: benchName.replace(/\.TO$/, '') }) : undefined
  const formatTime = useCallback((iso: string) => (range === '1D' ? etTime(iso, locale) : shortDate(iso, locale, true)), [range, locale])
  const formatValue = useCallback((v: number) => fmt(v), [fmt])

  useEffect(() => {
    if (!menuOpen) return
    const onDown = (e: MouseEvent) => { if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false) }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setMenuOpen(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey) }
  }, [menuOpen])

  useEffect(() => {
    if (!expanded) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setExpanded(false) }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [expanded])

  const rangeOptions = useMemo(() => RANGES.map((r) => ({
    value: r,
    label: (t.trackerUi.ranges as Record<string, string>)[r] ?? r,
    title: PREMIUM_RANGES.has(r) && !can('feature.full_history') ? t.trackerUi.premiumRange : undefined,
  })), [t, can])

  const gain = summary.total_gain
  const upgrade = history.error && isUpgrade(history.error)
  const chartArea = (height: number) => (
    upgrade ? (
      <PremiumHint body={tv.fullHistory} />
    ) : history.error && !h ? (
      <QueryError error={history.error} onRetry={() => history.refetch()} />
    ) : !h ? (
      <div className="rounded-xl animate-pulse" style={{ height, backgroundColor: theme.colors.surfaceAlt }} aria-busy="true" />
    ) : series.length < 2 ? (
      <p className="text-[13px] py-6 text-center" style={{ color: theme.colors.textSub }}>{tv.noSeries}</p>
    ) : (
      <div role="img" aria-label={fill(tv.chartAria, { range: rangeLabel, change: signedPct(change.pct) })}>
        <ValueChart series={series} compare={h.compare?.available ? h.compare.series : null}
          baseline={change.base} color={color} height={height}
          formatValue={formatValue} formatTime={formatTime} seriesLabel={tv.you} compareLabel={compareLabel} />
      </div>
    )
  )

  return (
    <section aria-labelledby="pv-title" className="rounded-2xl p-4 md:p-5 flex flex-col gap-3 min-w-0"
      style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.border}` }}>
      <div className="flex items-start justify-between gap-3 min-w-0">
        <div className="min-w-0">
          <h2 id="pv-title" className="text-[13px] font-medium" style={{ color: theme.colors.textSub }}>{tv.marketValue}</h2>
          <p className="text-[30px] md:text-[34px] font-bold leading-tight" style={{ color: theme.colors.text }}>
            <LiveValue value={String(summary.total)}>{fmt(summary.total)}</LiveValue>
          </p>
          <p className="text-[14px] font-semibold" style={{ color }}>
            <LiveValue value={`${change.abs}`}>
              {change.abs === null ? '—' : `${arrow(change.abs)}${fmt(Math.abs(change.abs))} ${signedPct(change.pct)}`}
            </LiveValue>
            <span className="ml-1.5 font-normal text-[12.5px]" style={{ color: theme.colors.textSub }}>{rangeLabel}</span>
          </p>
          <p className="text-[13px] mt-0.5" style={{ color: theme.colors.textSub }}>
            {gain.dividends_included ? tv.totalGainDivs : tv.totalGain}{' '}
            <span className="font-semibold tabular-nums" style={{ color: signColor(gain.abs) }}>
              {signed(gain.abs)} {gain.pct !== null ? `(${signedPct(gain.pct)})` : ''}
            </span>
          </p>
        </div>
        <button type="button" onClick={() => setExpanded(true)} aria-label={tv.expand} title={tv.expand}
          className="shrink-0 min-h-[44px] min-w-[44px] rounded-full inline-flex items-center justify-center focus-visible:outline focus-visible:outline-2"
          style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.textSub, outlineColor: theme.colors.primary }}>
          <Maximize2 size={16} aria-hidden="true" />
        </button>
      </div>

      {chartArea(200)}

      <ChipGroup value={range} options={rangeOptions} onChange={setRange} label={tv.rangeLabel}
        activeColor={change.abs === null ? undefined : color} />

      <div className="flex flex-wrap items-center gap-2">
        {compare ? (
          <button type="button" onClick={() => setCompare(null)}
            aria-label={fill(tv.removeCompare, { symbol: compare })}
            className="min-h-[44px] px-3 rounded-full text-[13px] font-medium inline-flex items-center gap-1.5 focus-visible:outline focus-visible:outline-2"
            style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.text, border: `1px dashed ${theme.colors.textSub}`, outlineColor: theme.colors.primary }}>
            {compareLabel}
            {h?.compare?.range_return_pct != null && (
              <span className="tabular-nums" style={{ color: signColor(h.compare.range_return_pct) }}>{signedPct(h.compare.range_return_pct)}</span>
            )}
            <X size={14} aria-hidden="true" />
          </button>
        ) : benchmarks.length > 0 && (
          <div className="relative" ref={menuRef}>
            <button type="button" onClick={() => setMenuOpen((o) => !o)} aria-haspopup="menu" aria-expanded={menuOpen}
              aria-controls={menuOpen ? menuId : undefined} aria-label={tv.compareLabel}
              className="min-h-[44px] px-3 rounded-full text-[13px] font-medium inline-flex items-center gap-1 focus-visible:outline focus-visible:outline-2"
              style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.text, outlineColor: theme.colors.primary }}>
              {tv.compare}<ChevronDown size={14} aria-hidden="true" />
            </button>
            {menuOpen && (
              <div id={menuId} role="menu" aria-label={tv.compareLabel}
                className="absolute left-0 top-full mt-1 z-20 min-w-[220px] max-w-[80vw] rounded-xl p-1 shadow-lg"
                style={{ backgroundColor: theme.colors.surfaceAlt, border: `1px solid ${theme.colors.border}` }}>
                {benchmarks.map((b) => (
                  <button key={b.symbol} type="button" role="menuitem" onClick={() => { setCompare(b.symbol); setMenuOpen(false) }}
                    className="w-full text-left min-h-[44px] px-3 rounded-lg text-[13px] focus-visible:outline focus-visible:outline-2"
                    style={{ color: theme.colors.text, outlineColor: theme.colors.primary }}>
                    <span className="font-semibold">{b.symbol.replace(/\.TO$/, '')}</span>
                    <span className="ml-2" style={{ color: theme.colors.textSub }}>{b.name}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        {h?.compare && !h.compare.available && (
          <span className="text-[12px]" style={{ color: theme.colors.textHint }}>{tv.compareUnavailable}</span>
        )}
      </div>

      <div className="flex flex-col gap-0.5">
        <Freshness asOf={h?.as_of ?? summary.as_of} delayed={h?.delayed_minutes ?? summary.delayed_minutes} />
        {h && range !== '1D' && h.estimated && (h.estimated_reason === 'no_snapshots' || h.estimated_reason === 'partial_snapshots') && (
          <p className="text-[12px]" style={{ color: theme.colors.textHint }}>
            {tv.estimated}{' '}
            <Link href="/profile/transactions" className="underline underline-offset-2 font-medium" style={{ color: theme.colors.primary }}>
              {tv.addTransactions}
            </Link>
          </p>
        )}
        {h && range === '1D' && h.estimated_reason === 'no_intraday' && (
          <p className="text-[12px]" style={{ color: theme.colors.textHint }}>{tv.noIntraday}</p>
        )}
      </div>

      {expanded && (
        <div role="dialog" aria-modal="true" aria-labelledby="pv-full-title"
          className="fixed inset-0 z-50 p-4 md:p-8 flex flex-col gap-3"
          style={{ backgroundColor: theme.colors.bg }}>
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h2 id="pv-full-title" className="text-[13px] font-medium" style={{ color: theme.colors.textSub }}>{tv.marketValue}</h2>
              <p className="text-[26px] font-bold tabular-nums" style={{ color: theme.colors.text }}>{fmt(summary.total)}</p>
              <p className="text-[14px] font-semibold tabular-nums" style={{ color }}>
                {change.abs === null ? '—' : `${arrow(change.abs)}${fmt(Math.abs(change.abs))} ${signedPct(change.pct)}`}
                <span className="ml-1.5 font-normal text-[12.5px]" style={{ color: theme.colors.textSub }}>{rangeLabel}</span>
              </p>
            </div>
            <button type="button" onClick={() => setExpanded(false)} aria-label={t.tracker.close} autoFocus
              className="shrink-0 min-h-[44px] min-w-[44px] rounded-full inline-flex items-center justify-center focus-visible:outline focus-visible:outline-2"
              style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.text, outlineColor: theme.colors.primary }}>
              <X size={18} aria-hidden="true" />
            </button>
          </div>
          <div className="flex-1 min-h-0">{chartArea(typeof window !== 'undefined' ? Math.max(240, window.innerHeight - 260) : 400)}</div>
          <ChipGroup value={range} options={rangeOptions} onChange={setRange} label={tv.rangeLabel}
            activeColor={change.abs === null ? undefined : color} />
        </div>
      )}
    </section>
  )
}

/** Compact value card for /home: total, total gain, today's change. */
export function HomeValueCard({ summary, href }: { summary: PortfolioSummary; href: string }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const tv = t.trackerUi.value
  const { fmt, signed } = useMoney(summary.currency)
  const signColor = useSignColor()
  const dc = summary.day_change
  const gain = summary.total_gain
  return (
    <section aria-labelledby="home-value" className="rounded-2xl p-4 md:p-5 flex flex-col gap-2 min-w-0"
      style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.border}` }}>
      <div className="flex items-baseline justify-between gap-2">
        <h2 id="home-value" className="text-[13px] font-medium" style={{ color: theme.colors.textSub }}>{t.home.valueTitle}</h2>
        <Link href={href} className="text-[13px] font-medium min-h-[44px] inline-flex items-center px-1 focus-visible:outline focus-visible:outline-2 rounded"
          style={{ color: theme.colors.primary, outlineColor: theme.colors.primary }}>
          {t.home.openHoldings}
        </Link>
      </div>
      <p className="text-[30px] font-bold leading-tight" style={{ color: theme.colors.text }}>
        <LiveValue value={String(summary.total)}>{fmt(summary.total)}</LiveValue>
      </p>
      <p className="text-[14px] font-semibold" style={{ color: signColor(dc.abs) }}>
        <LiveValue value={`${dc.abs}`}>
          {dc.abs === null ? '—' : `${arrow(dc.abs)}${fmt(Math.abs(dc.abs))} ${signedPct(dc.pct)}`}
        </LiveValue>
        <span className="ml-1.5 font-normal text-[12.5px]" style={{ color: theme.colors.textSub }}>{tv.today}</span>
      </p>
      <div className="text-[13px] flex flex-col gap-0.5" style={{ color: theme.colors.textSub }}>
        <p>
          {tv.totalGain}{' '}
          <span className="font-semibold tabular-nums" style={{ color: signColor(gain.abs) }}>
            {signed(gain.abs)} {gain.pct !== null ? `(${signedPct(gain.pct)})` : ''}
          </span>
        </p>
        <p className="text-[12px]" style={{ color: theme.colors.textHint }}>
          {gain.dividends_included ? tv.includesDividends : tv.excludesDividends}
        </p>
      </div>
      <Freshness asOf={summary.as_of} delayed={summary.delayed_minutes} />
    </section>
  )
}
