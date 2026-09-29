'use client'

import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { Panel, mono } from '@/components/insights/Panel'
import { fill, shortDate } from '@/lib/insights'
import type { LongCheckResult } from '@/types/check'
import { periodLabel, spct, spp } from './format'

/** 1/3/5/10y CAGR vs the benchmark. Four narrow columns fit a 390px phone;
 *  the table still scrolls inside its own box if a label is unusually wide. */
export function ReturnsTable({ result: r }: { result: LongCheckResult }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const tl = t.check.long
  const bench = r.benchmark
  const converted = !!bench && (r.currency ?? 'USD') !== (bench.endsWith('.TO') ? 'CAD' : 'USD')
    && !r.notes.some((n) => n.code.startsWith('benchmark_'))
  const si = r.drawdowns.since_inception
  const th = 'text-[11px] font-medium px-2 py-2 text-right whitespace-nowrap'
  const td = 'px-2 py-2.5 text-right align-top'

  return (
    <Panel
      title={bench ? fill(tl.returnsTitle, { benchmark: bench }) : tl.returnsTitleNone}
      subtitle={tl.returnsSubtitle}
    >
      {r.returns.length === 0 ? (
        <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{tl.noReturns}</p>
      ) : (
        <div className="overflow-x-auto -mx-1 px-1" tabIndex={0} role="region" aria-label={bench ? fill(tl.returnsTitle, { benchmark: bench }) : tl.returnsTitleNone}>
          <table className="w-full border-collapse tabular-nums" style={mono}>
            <thead>
              <tr style={{ color: theme.colors.textSub, borderBottom: `1px solid ${theme.colors.border}` }}>
                <th scope="col" className={`${th} text-left`} style={{ fontFamily: 'inherit' }}>{tl.period}</th>
                <th scope="col" className={th}>{r.symbol}</th>
                <th scope="col" className={th}>{bench ?? tl.noBenchmark}</th>
                <th scope="col" className={th}>
                  <abbr title={tl.excessHelp} style={{ textDecoration: 'none' }}>{tl.excess}</abbr>
                </th>
              </tr>
            </thead>
            <tbody>
              {r.returns.map((row) => {
                const ex = row.excess_cagr
                const exColor = ex == null ? theme.colors.textHint : ex >= 0 ? theme.colors.up : theme.colors.down
                return (
                  <tr key={row.period} style={{ borderBottom: `1px solid ${theme.colors.border}` }}>
                    <th scope="row" className="px-2 py-2.5 text-left text-[13px] font-medium align-top" style={{ color: theme.colors.text }}>
                      {periodLabel(row.years, t)}
                    </th>
                    <td className={td}>
                      <div className="text-[14px]" style={{ color: theme.colors.text }}>{spct(row.asset_cagr)}</div>
                      <div className="text-[11px]" style={{ color: theme.colors.textSub }}>{fill(tl.total, { v: spct(row.asset_total, 0) })}</div>
                    </td>
                    <td className={td}>
                      <div className="text-[14px]" style={{ color: theme.colors.text }}>{spct(row.benchmark_cagr)}</div>
                      {row.benchmark_total != null && (
                        <div className="text-[11px]" style={{ color: theme.colors.textSub }}>{fill(tl.total, { v: spct(row.benchmark_total, 0) })}</div>
                      )}
                    </td>
                    <td className={td}>
                      <div className="text-[14px] font-semibold" style={{ color: exColor }}>{spp(ex)}</div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      <div className="mt-3 flex flex-col gap-1">
        {si && si.cagr != null && (
          <p className="text-[12px]" style={{ color: theme.colors.textSub }}>
            {fill(tl.sinceInception, { date: shortDate(si.start, locale, true), cagr: spct(si.cagr), total: spct(si.total, 0) })}
          </p>
        )}
        {converted && (
          <p className="text-[12px]" style={{ color: theme.colors.textSub }}>
            {fill(tl.returnsBenchCcy, { benchmark: bench, currency: r.currency })}
          </p>
        )}
      </div>
    </Panel>
  )
}
