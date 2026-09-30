'use client'

import { memo, useMemo } from 'react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore, intlLocale } from '@/store/i18nStore'
import { DASH, nativePrice } from '@/lib/insights'
import { Panel } from '@/components/insights/Panel'
import { compactMoney } from '@/components/stock/StockChecks'
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

/** Key statistics grid (shared part of GET /stocks/{symbol}); nulls show "—". */
export function StockStatistics({ stats, symbol, currency }: { stats: Stats | undefined; symbol: string; currency: string }) {
  const t = useI18nStore((s) => s.t)
  const ts = t.stock.stats
  const cells = useMemo(() => {
    if (!stats) return []
    const range = (lo: number | null, hi: number | null) =>
      lo === null && hi === null ? DASH : `${nativePrice(lo, symbol, currency)} – ${nativePrice(hi, symbol, currency)}`
    return [
      { key: 'day', label: ts.dayRange, value: range(stats.day_low, stats.day_high) },
      { key: '52w', label: ts.range52w, value: range(stats.low_52w, stats.high_52w) },
      { key: 'cap', label: ts.marketCap, value: compactMoney(stats.market_cap, currency) },
      { key: 'pe', label: ts.pe, value: fixed(stats.pe_ratio) },
      { key: 'fpe', label: ts.forwardPe, value: fixed(stats.forward_pe) },
      { key: 'yield', label: ts.yield, value: stats.dividend_yield === null ? DASH : `${fixed(stats.dividend_yield * 100)}%` },
      { key: 'vol', label: ts.volume, value: compactNum(stats.volume) },
      { key: 'avgvol', label: ts.avgVolume, value: compactNum(stats.avg_volume) },
      { key: 'beta', label: ts.beta, value: fixed(stats.beta) },
    ]
  }, [stats, symbol, currency, ts])
  if (!stats) return null
  return (
    <Panel title={ts.title}>
      <dl className="grid grid-cols-2 sm:grid-cols-3 gap-2">
        {cells.map((c) => <Cell key={c.key} label={c.label} value={c.value} />)}
      </dl>
    </Panel>
  )
}
