'use client'

import { memo, useMemo } from 'react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore, intlLocale } from '@/store/i18nStore'
import { DASH, nativePrice } from '@/lib/insights'
import { Panel } from '@/components/insights/Panel'
import type { StockStatistics as Stats } from '@/types/stock'

function compactNum(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return DASH
  return v.toLocaleString(intlLocale(), { notation: 'compact', maximumFractionDigits: 1 })
}

function fixed(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return DASH
  return v.toLocaleString(intlLocale(), { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

const Cell = memo(function Cell({ label, value }: { label: string; value: string }) {
  const theme = useTheme()
  return (
    <div className="rounded-xl px-3 py-2.5 min-w-0 flex flex-col gap-0.5" style={{ backgroundColor: theme.colors.surfaceAlt }}>
      <dt className="text-[12px]" style={{ color: theme.colors.textSub }}>{label}</dt>
      <dd className="text-[14.5px] font-semibold tabular-nums break-words" style={{ color: value === DASH ? theme.colors.textHint : theme.colors.text }}>
        {value}
      </dd>
    </div>
  )
})

/** Key statistics grid (shared part of GET /stocks/{symbol}). Stats without
 *  a value (most of them for ETFs) are left out; the 52-week range and market
 *  cap are in the page header and the yield on the Dividends tab. */
export function StockStatistics({ stats, symbol, currency, price }: {
  stats: Stats | undefined; symbol: string; currency: string; price?: number | null
}) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const ts = t.stock.stats
  const cells = useMemo(() => {
    if (!stats) return []
    return [
      { key: 'pe', label: ts.pe, value: fixed(stats.pe_ratio) },
      { key: 'fpe', label: ts.forwardPe, value: fixed(stats.forward_pe) },
      { key: 'vol', label: ts.volume, value: compactNum(stats.volume) },
      { key: 'avgvol', label: ts.avgVolume, value: compactNum(stats.avg_volume) },
      { key: 'beta', label: ts.beta, value: fixed(stats.beta) },
    ].filter((c) => c.value !== DASH)
  }, [stats, ts])
  const day = stats && stats.day_low != null && stats.day_high != null && stats.day_high >= stats.day_low
    ? { lo: stats.day_low, hi: stats.day_high } : null
  if (!stats || (cells.length === 0 && !day)) return null
  const mark = day && price != null && day.hi > day.lo
    ? Math.min(100, Math.max(0, ((price - day.lo) / (day.hi - day.lo)) * 100)) : 50
  return (
    <Panel title={ts.title}>
      {day && (
        <div className="mb-3 min-w-0">
          <p className="text-[12px] mb-1.5" style={{ color: theme.colors.textSub }}>{ts.dayRange}</p>
          <div className="h-1.5 rounded-full relative" style={{ backgroundColor: theme.colors.surfaceAlt }} role="img"
            aria-label={`${ts.dayRange}: ${nativePrice(day.lo, symbol, currency)} – ${nativePrice(day.hi, symbol, currency)}`}>
            {price != null && (
              <div className="absolute w-3 h-3 rounded-full -top-[3px]"
                style={{ backgroundColor: theme.colors.primary, border: `2px solid ${theme.colors.surface}`, left: `${mark}%`, transform: 'translateX(-50%)' }} />
            )}
          </div>
          <div className="flex justify-between mt-1.5 text-[11.5px] tabular-nums" style={{ color: theme.colors.textHint }}>
            <span>{nativePrice(day.lo, symbol, currency)}</span><span>{nativePrice(day.hi, symbol, currency)}</span>
          </div>
        </div>
      )}
      <dl className="grid grid-cols-2 sm:grid-cols-3 gap-2">
        {cells.map((c) => <Cell key={c.key} label={c.label} value={c.value} />)}
      </dl>
    </Panel>
  )
}
