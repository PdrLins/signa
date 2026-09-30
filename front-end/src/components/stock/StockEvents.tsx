'use client'

import { memo, useMemo } from 'react'
import { CalendarDays } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { Panel } from '@/components/insights/Panel'
import { fill, nativePrice, shortDate } from '@/lib/insights'
import type { StockEvents as Events } from '@/types/stock'

interface Row {
  key: string
  label: string
  date: string
  when: string | null
  estimated: boolean
  extra: string | null
}

function daysUntil(iso: string): number | null {
  const d = new Date(`${iso}T12:00:00Z`)
  if (Number.isNaN(d.getTime())) return null
  const now = new Date()
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate(), 12)
  return Math.round((d.getTime() - today) / 86_400_000)
}

const EventRow = memo(function EventRow({ row, estLabel }: { row: Row; estLabel: string }) {
  const theme = useTheme()
  return (
    <li className="flex items-start justify-between gap-3 py-2.5 min-w-0" style={{ borderBottom: `1px solid ${theme.colors.border}` }}>
      <div className="min-w-0">
        <p className="text-[13px] font-medium" style={{ color: theme.colors.text }}>{row.label}</p>
        {row.extra && <p className="text-[12px]" style={{ color: theme.colors.textSub }}>{row.extra}</p>}
      </div>
      <div className="text-right shrink-0">
        <p className="text-[13px] tabular-nums" style={{ color: theme.colors.text }}>
          {row.date}
          {row.estimated && (
            <span className="ml-1.5 inline-block text-[10.5px] font-semibold px-1.5 py-px rounded-full align-middle"
              style={{ color: theme.colors.textSub, border: `1px solid ${theme.colors.textSub}` }}>
              {estLabel}
            </span>
          )}
        </p>
        {row.when && <p className="text-[11.5px]" style={{ color: theme.colors.textHint }}>{row.when}</p>}
      </div>
    </li>
  )
})

/** Next earnings, ex-dividend and payment dates ("estimated" when projected). */
export function StockEvents({ events, symbol, currency }: { events: Events; symbol: string; currency: string | null }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const te = t.stock.events

  const rows = useMemo(() => {
    const when = (iso: string, days?: number | null) => {
      const n = days ?? daysUntil(iso)
      if (n === null || n < 0) return null
      return n === 0 ? te.today : fill(te.inDays, { n })
    }
    const out: Row[] = []
    const e = events.earnings
    if (e?.date) {
      out.push({ key: 'earnings', label: te.earnings, date: shortDate(e.date, locale, true), when: when(e.date, e.days),
        estimated: false, extra: null })
    }
    const ex = events.ex_dividend
    if (ex) {
      out.push({ key: 'ex', label: te.exDividend, date: shortDate(ex.date, locale, true), when: when(ex.date),
        estimated: ex.estimated,
        extra: ex.amount != null ? fill(te.amount, { amount: nativePrice(ex.amount, symbol, currency) }) : null })
    }
    const pay = events.dividend_payment
    if (pay) {
      out.push({ key: 'pay', label: te.payment, date: shortDate(pay.date, locale, true), when: when(pay.date),
        estimated: pay.estimated, extra: null })
    }
    return out
  }, [events, te, locale, symbol, currency])

  return (
    <Panel title={<span className="flex items-center gap-2"><CalendarDays size={17} aria-hidden="true" style={{ color: theme.colors.primary }} />{t.stock.eventsTitle}</span>}>
      {rows.length === 0 ? (
        <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{te.none}</p>
      ) : (
        <div className="flex flex-col gap-2">
          <ul className="flex flex-col">
            {rows.map((r) => <EventRow key={r.key} row={r} estLabel={te.estimated} />)}
          </ul>
          {events.ex_dividend && (
            <p className="text-[11.5px] leading-snug" style={{ color: theme.colors.textHint }}>{te.exHelp}</p>
          )}
        </div>
      )}
    </Panel>
  )
}
