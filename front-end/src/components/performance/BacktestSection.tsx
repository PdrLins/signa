'use client'

import { useTheme } from '@/hooks/useTheme'
import { useI18nStore, intlLocale } from '@/store/i18nStore'
import { Panel } from '@/components/insights/Panel'
import { fill, signedPct, shortDate } from '@/lib/insights'
import type { BacktestInsights, BacktestBand } from '@/types/insights'

function BandBars({ rows }: { rows: BacktestBand[] }) {
  const theme = useTheme()
  const scale = Math.max(0.1, ...rows.map((r) => Math.abs(r.avg_excess_vs_spy_pct ?? 0)))
  return (
    <ul className="flex flex-col gap-2">
      {rows.map((b) => {
        const v = b.avg_excess_vs_spy_pct
        const w = v == null ? 0 : Math.min(50, (Math.abs(v) / scale) * 50)
        return (
          <li key={b.band} className="grid grid-cols-[minmax(0,110px)_minmax(0,1fr)_64px_72px] gap-3 items-center">
            <span className="text-[13px] truncate" style={{ color: theme.colors.text, fontFamily: 'var(--font-mono)' }} title={b.band}>{b.band}</span>
            <div className="relative h-[18px]" aria-hidden="true">
              <div className="absolute left-1/2 top-0 bottom-0 w-px" style={{ backgroundColor: theme.colors.textSub + '66' }} />
              {v != null && (
                <div className="absolute top-1 h-2.5 rounded-[3px]" style={{ left: v >= 0 ? '50%' : `${50 - w}%`, width: `${Math.max(w, 0.5)}%`, backgroundColor: v >= 0 ? theme.colors.up : theme.colors.down }} />
              )}
            </div>
            <span className="text-[13px] text-right tabular-nums" style={{ color: theme.colors.text, fontFamily: 'var(--font-mono)' }}>{signedPct(v)}</span>
            <span className="text-[12px] text-right tabular-nums" style={{ color: theme.colors.textSub, fontFamily: 'var(--font-mono)' }}>n={b.trades.toLocaleString(intlLocale())}</span>
          </li>
        )
      })}
    </ul>
  )
}

export function BacktestSection({ data }: { data: BacktestInsights }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const b = t.performance.backtest
  const latest = data.latest
  if (!latest) {
    return <Panel title={fill(b.title, { start: '', end: '' })}><p className="text-sm" style={{ color: theme.colors.textSub }}>{b.empty}</p></Panel>
  }
  const row = (label: string, value: string, sub?: string) => (
    <div className="flex justify-between gap-3 text-sm">
      <span style={{ color: theme.colors.textSub }}>{label}{sub && <span className="block text-[11px]">{sub}</span>}</span>
      <span className="tabular-nums shrink-0" style={{ color: theme.colors.text, fontFamily: 'var(--font-mono)' }}>{value}</span>
    </div>
  )
  const spy = latest.benchmarks?.SPY
  const xiu = latest.benchmarks?.['XIU.TO']

  return (
    <Panel
      title={fill(b.title, { start: shortDate(latest.start, locale, true), end: shortDate(latest.end, locale, true) })}
      right={<span className="text-[12px] font-semibold uppercase tracking-wide" style={{ color: theme.colors.up }}>{b.real}</span>}
    >
      <div className="grid grid-cols-1 lg:grid-cols-[320px_minmax(0,1fr)] gap-6 lg:gap-8 items-start">
        <div className="flex flex-col gap-3">
          {spy && row(b.spy, signedPct(spy.total_return_pct, 1))}
          {xiu && row(b.xiu, signedPct(xiu.total_return_pct, 1))}
          {data.runs.map((r) => row(fill(b.run, { rule: r.entry_rule ?? r.name }), signedPct(r.total_return_pct, 1), fill(b.trades, { n: r.trades.toLocaleString(intlLocale()) })))}
          <p className="mt-1 text-[12px] leading-relaxed" style={{ color: theme.colors.textSub }}>{b.note}</p>
        </div>
        <div className="flex flex-col gap-2 min-w-0">
          <span className="text-[13px]" style={{ color: theme.colors.textSub }}>
            {fill(b.bandsTitle, { n: (latest.study_trades ?? 0).toLocaleString(intlLocale()) })}
          </span>
          <BandBars rows={latest.by_band} />
          <span className="text-[12px]" style={{ color: theme.colors.warning }}>{b.bandsNote}</span>
          {latest.by_filter && latest.by_filter.length > 0 && (
            <div className="mt-4 flex flex-col gap-2">
              <span className="text-[13px]" style={{ color: theme.colors.textSub }}>{b.filterTitle}</span>
              <BandBars rows={latest.by_filter} />
            </div>
          )}
        </div>
      </div>
      {latest.caveats.length > 0 && (
        <details className="mt-5">
          <summary className="cursor-pointer text-[13px] rounded focus-visible:outline focus-visible:outline-2" style={{ color: theme.colors.accent, outlineColor: theme.colors.primary }}>
            {b.showCaveats}
          </summary>
          <ul className="mt-2 flex flex-col gap-1.5 list-disc pl-5">
            {latest.caveats.map((c, i) => <li key={i} className="text-[12px] leading-relaxed" style={{ color: theme.colors.textSub }}>{c}</li>)}
          </ul>
        </details>
      )}
    </Panel>
  )
}
