'use client'

import { useMemo, useState } from 'react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore, INTL_LOCALES } from '@/store/i18nStore'
import { useScope, useUpcomingEvents } from '@/hooks/usePortfolioInsights'
import { fill } from '@/lib/insights'
import { EventRow } from '@/components/tracker/EventRow'
import { ChipGroup, EmptyHoldings, Freshness, QueryError, SkeletonCards } from '@/components/tracker/ui'
import type { EventItem } from '@/types/tracker'

const DAYS = ['7', '30', '90'] as const

/** The "Coming up" timeline: dividends, earnings, economy dates and recent
 *  alerts for the stocks in scope, grouped by day (GET /events/upcoming).
 *  Lives on the Dividends page (Coming up tab). */
export function EventsTimeline() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const tc = t.comingUpPage
  const { scope, scoped } = useScope()
  const [days, setDays] = useState<string>('30')
  const q = useUpcomingEvents(scope, Number(days))
  const d = q.data
  const dayOptions = useMemo(() => DAYS.map((v) => ({ value: v as string, label: fill(tc.daysChip, { n: v }) })), [tc])

  const { recent, groups } = useMemo(() => {
    const recentItems: EventItem[] = []
    const byDay = new Map<string, EventItem[]>()
    for (const ev of d?.items ?? []) {
      if (ev.recent) { recentItems.push(ev); continue }
      const list = byDay.get(ev.date)
      if (list) list.push(ev)
      else byDay.set(ev.date, [ev])
    }
    return { recent: recentItems, groups: Array.from(byDay.entries()).sort((a, b) => (a[0] < b[0] ? -1 : 1)) }
  }, [d])

  const dayLabel = (iso: string) => {
    const date = new Date(`${iso}T12:00:00Z`)
    if (Number.isNaN(date.getTime())) return iso
    const s = date.toLocaleDateString(INTL_LOCALES[locale], { weekday: 'long', month: 'long', day: 'numeric', timeZone: 'UTC' })
    return d && iso === d.today ? fill(tc.todayLabel, { date: s }) : s
  }
  const failed = d ? Object.entries(d.sources).filter(([, v]) => v === 'failed' || v === 'unavailable').map(([k]) => (tc.sources as Record<string, string>)[k] ?? k) : []
  const noSymbols = !!d && d.symbols.held.length === 0 && d.symbols.watched.length === 0 && !scoped

  return (
    <div className="space-y-4 min-w-0 max-w-3xl">
      <p className="text-[13px] max-w-2xl" style={{ color: theme.colors.textSub }}>{tc.subtitle}</p>
      <ChipGroup value={days} options={dayOptions} onChange={setDays} label={tc.daysLabel} />

      {q.isLoading && <SkeletonCards heights={[120, 160, 160]} />}
      {!!q.error && !d && <QueryError error={q.error} onRetry={() => q.refetch()} />}
      {noSymbols && <EmptyHoldings body={tc.emptyBody} />}

      {d && (
        <div className="flex flex-col gap-4 min-w-0" aria-busy={q.isFetching}>
          {failed.length > 0 && (
            <p role="status" className="text-[12.5px] rounded-xl px-3 py-2" style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.warning }}>
              {fill(tc.sourcesFailed, { sources: failed.join(', ') })}
            </p>
          )}
          {groups.length === 0 && recent.length === 0 && (
            <p className="text-[14px] rounded-2xl p-4" style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.border}`, color: theme.colors.textSub }}>
              {fill(tc.none, { n: days })}
            </p>
          )}
          {groups.map(([date, items]) => (
            <section key={date} aria-labelledby={`day-${date}`} className="rounded-2xl px-4 pt-3 pb-1 min-w-0"
              style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.border}` }}>
              <h2 id={`day-${date}`} className="text-[14px] font-semibold pb-2 first-letter:uppercase" style={{ color: theme.colors.text }}>{dayLabel(date)}</h2>
              <ul>
                {items.map((ev, i) => <EventRow key={`${ev.type}-${ev.symbol}-${i}`} ev={ev} currency={d.home_currency} />)}
              </ul>
            </section>
          ))}
          {recent.length > 0 && (
            <section aria-labelledby="recent-events" className="rounded-2xl px-4 pt-3 pb-1 min-w-0"
              style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.border}` }}>
              <h2 id="recent-events" className="text-[14px] font-semibold" style={{ color: theme.colors.text }}>{tc.recentTitle}</h2>
              <p className="text-[12.5px] pb-2" style={{ color: theme.colors.textSub }}>{tc.recentHelp}</p>
              <ul>
                {recent.map((ev, i) => (
                  <EventRow key={`${ev.type}-${ev.symbol}-${ev.date}-${i}`} ev={ev} currency={d.home_currency}
                    showDate={new Date(`${ev.date}T12:00:00Z`).toLocaleDateString(INTL_LOCALES[locale], { month: 'short', day: 'numeric', timeZone: 'UTC' })} />
                ))}
              </ul>
            </section>
          )}
          <Freshness asOf={d.as_of} delayed={d.delayed_minutes} />
          <p className="text-[12px]" style={{ color: theme.colors.textHint }}>{tc.economyNote}</p>
        </div>
      )}
    </div>
  )
}
