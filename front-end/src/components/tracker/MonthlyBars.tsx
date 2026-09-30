'use client'

import { memo, useMemo } from 'react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore, INTL_LOCALES, type Locale } from '@/store/i18nStore'
import { fill } from '@/lib/insights'
import type { DividendSummaryMonth } from '@/types/tracker'

function monthLabel(key: string, locale: string, short: boolean): string {
  const d = new Date(`${key}-15T12:00:00Z`)
  if (Number.isNaN(d.getTime())) return key
  return d.toLocaleDateString(INTL_LOCALES[locale as Locale] ?? 'en-CA', short
    ? { month: 'narrow', timeZone: 'UTC' }
    : { month: 'long', year: 'numeric', timeZone: 'UTC' })
}

/** 12 monthly bars, steady (bottom) + variable (top), drawn to scale. */
export const MonthlyBars = memo(function MonthlyBars({ months, fmt }: {
  months: DividendSummaryMonth[]
  fmt: (v: number) => string
}) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const td = t.divSummary
  const max = useMemo(() => Math.max(0, ...months.map((m) => m.steady + m.variable)), [months])
  if (max <= 0) return <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{td.noBars}</p>
  return (
    <div className="flex flex-col gap-2 min-w-0">
      <ol aria-label={td.barsAria} className="flex items-end gap-1 sm:gap-2 h-36 min-w-0">
        {months.map((m) => {
          const total = m.steady + m.variable
          const label = fill(td.barLabel, {
            month: monthLabel(m.month, locale, false), total: fmt(total), steady: fmt(m.steady), variable: fmt(m.variable),
          })
          return (
            <li key={m.month} aria-label={label} title={label} className="flex-1 min-w-0 h-full flex flex-col items-center justify-end gap-1">
              <div className="w-full flex-1 flex flex-col justify-end">
                <div className="w-full rounded-t-[3px]" style={{ height: `${(m.variable / max) * 100}%`, backgroundColor: theme.colors.warning }} />
                <div className="w-full" style={{
                  height: `${(m.steady / max) * 100}%`, minHeight: total > 0 ? 2 : 0, backgroundColor: theme.colors.primary,
                  borderTopLeftRadius: m.variable > 0 ? 0 : 3, borderTopRightRadius: m.variable > 0 ? 0 : 3,
                }} />
              </div>
              <span aria-hidden="true" className="text-[10px] uppercase" style={{ color: theme.colors.textSub }}>
                {monthLabel(m.month, locale, true)}
              </span>
            </li>
          )
        })}
      </ol>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-[12px]" style={{ color: theme.colors.textSub }}>
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden="true" className="w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: theme.colors.primary }} />{td.steady}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden="true" className="w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: theme.colors.warning }} />{td.variable}
        </span>
      </div>
    </div>
  )
})
