'use client'

import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { Panel, mono } from '@/components/insights/Panel'
import { DASH, fill, nativePrice, shortDate } from '@/lib/insights'
import type { LongCheckResult } from '@/types/check'
import { fixed, spct } from './format'

/** Worst fall + recovery, distance from the all-time high, worst year,
 *  volatility, and a small calendar-year strip. */
export function DrawdownCard({ result: r }: { result: LongCheckResult }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const tl = t.check.long
  const d = r.drawdowns
  const mdd = d.max
  const cur = d.current
  const date = (s: string | null | undefined) => shortDate(s ?? null, locale, true)

  const tiles: { k: string; v: string; sub?: string; color?: string }[] = [
    {
      k: tl.maxDrawdown,
      v: mdd ? spct(mdd.depth_pct) : DASH,
      sub: mdd?.peak_date ? fill(tl.maxDrawdownDates, { peak: date(mdd.peak_date), trough: date(mdd.trough_date) }) : undefined,
      color: theme.colors.down,
    },
    {
      k: tl.recovery,
      v: !mdd || !mdd.peak_date ? DASH : mdd.recovered ? fill(tl.daysValue, { n: mdd.recovery_days }) : tl.notRecovered,
      sub: !mdd || !mdd.peak_date ? undefined
        : mdd.recovered ? fill(tl.recoveredIn, { days: mdd.recovery_days, date: date(mdd.recovery_date) })
          : fill(tl.underwater, { days: mdd.underwater_days }),
      color: mdd && !mdd.recovered ? theme.colors.warning : undefined,
    },
    {
      k: tl.currentDrawdown,
      v: cur ? (cur.pct >= -0.05 ? tl.atHigh : spct(cur.pct)) : DASH,
      sub: cur ? fill(tl.athOn, { price: nativePrice(cur.ath, r.symbol, r.currency), date: date(cur.ath_date) }) : undefined,
    },
    {
      k: tl.worstYear,
      v: d.worst_year ? spct(d.worst_year.return) : DASH,
      sub: d.worst_year ? String(d.worst_year.year) : undefined,
    },
    { k: tl.volatility, v: d.volatility != null ? fill(tl.volatilityValue, { v: fixed(d.volatility, 0) }) : DASH },
    { k: tl.history, v: fill(tl.historyValue, { years: fixed(d.history_years, 1) }) },
  ]

  const years = d.calendar_years.slice(-10)
  const maxAbs = Math.max(1, ...years.map((y) => Math.abs(y.return)))

  return (
    <Panel title={tl.drawdownTitle}>
      <dl className="grid grid-cols-1 min-[360px]:grid-cols-2 gap-2.5">
        {tiles.map((x) => (
          <div key={x.k} className="rounded-[10px] px-3 py-2.5 flex flex-col gap-1 min-w-0" style={{ backgroundColor: theme.colors.surfaceAlt }}>
            <dt className="text-[11px]" style={{ color: theme.colors.textSub }}>{x.k}</dt>
            <dd className="text-[15px] tabular-nums break-words" style={{ ...mono, color: x.color ?? theme.colors.text }}>{x.v}</dd>
            {x.sub && <dd className="text-[11px] break-words" style={{ color: theme.colors.textSub }}>{x.sub}</dd>}
          </div>
        ))}
      </dl>

      {years.length > 1 && (
        <div className="mt-4 flex flex-col gap-2">
          <h3 className="text-[13px] font-semibold" style={{ color: theme.colors.text }}>{tl.calendarYears}</h3>
          <ul className="flex flex-col gap-1">
            {years.map((y) => {
              const w = (Math.abs(y.return) / maxAbs) * 50
              const pos = y.return >= 0
              return (
                <li key={y.year} className="grid grid-cols-[3rem_minmax(0,1fr)_4rem] items-center gap-2 text-[12px] tabular-nums" style={mono}>
                  <span style={{ color: theme.colors.textSub }}>{y.year}</span>
                  <span className="relative h-2.5 rounded-full" aria-hidden="true" style={{ backgroundColor: theme.colors.surfaceAlt }}>
                    <span className="absolute top-0 bottom-0 w-px" style={{ left: '50%', backgroundColor: theme.colors.border }} />
                    <span
                      className="absolute top-0 bottom-0 rounded-full"
                      style={{
                        left: pos ? '50%' : `${50 - w}%`,
                        width: `${w}%`,
                        backgroundColor: pos ? theme.colors.up : theme.colors.down,
                      }}
                    />
                  </span>
                  <span className="text-right" style={{ color: pos ? theme.colors.text : theme.colors.down }}>{spct(y.return)}</span>
                </li>
              )
            })}
          </ul>
        </div>
      )}
    </Panel>
  )
}
