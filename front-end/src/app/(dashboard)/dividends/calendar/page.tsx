'use client'

import { memo, useCallback, useMemo, useState, type ReactNode } from 'react'
import Link from 'next/link'
import { ArrowLeft, CalendarDays } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore, INTL_LOCALES, type Locale } from '@/store/i18nStore'
import { useDividendCalendar } from '@/hooks/useDividendCalendar'
import { toHoldingsError } from '@/hooks/useHoldings'
import { DASH, fill, shortDate } from '@/lib/insights'
import { money, num } from '@/components/holdings/format'
import { Skeleton } from '@/components/ui/Skeleton'
import type en from '@/lib/i18n/en.json'
import type { DividendCalendarResponse, DividendEvent, DividendMoney, DividendMonth } from '@/types/dividends'

type TD = typeof en['dividendsPage']

// ── pure helpers ─────────────────────────────────────────────

function intl(locale: string): string {
  return INTL_LOCALES[locale as Locale] ?? 'en-CA'
}

/** "2026-10" -> "October 2026" / "Oct" */
function monthLabel(key: string, locale: string, short = false): string {
  const d = new Date(`${key}-15T12:00:00Z`)
  if (Number.isNaN(d.getTime())) return key
  return d.toLocaleDateString(intl(locale), short
    ? { month: 'short', timeZone: 'UTC' }
    : { month: 'long', year: 'numeric', timeZone: 'UTC' })
}

/** Per-share amount: 2-4 decimals as needed ("US$0.91", "C$0.3125"). */
function perShare(v: number | null, currency: string, locale: string): string {
  if (v === null || !Number.isFinite(v)) return DASH
  const decimals = (v.toFixed(4).split('.')[1] ?? '').replace(/0+$/, '').length
  const digits = Math.min(4, Math.max(2, decimals))
  return money(v, currency, locale, digits)
}

/** "US$27.30 + C$222.00" */
function splitText(m: DividendMoney, locale: string): string {
  const parts = Object.entries(m.by_currency).map(([c, v]) => money(v, c, locale))
  return parts.length ? parts.join(' + ') : DASH
}

function symbolsText(items: { symbol: string }[]): string {
  return items.map((i) => i.symbol).join(', ')
}

// ── small pieces ─────────────────────────────────────────────

const Tag = memo(function Tag({ label, title, color }: { label: string; title?: string; color: string }) {
  return (
    <span title={title} className="inline-block text-[10.5px] font-semibold px-1.5 py-px rounded-full whitespace-nowrap"
      style={{ color, border: `1px solid ${color}` }}>
      {label}
    </span>
  )
})

const Card = memo(function Card({ label, children, id }: { label: string; children: ReactNode; id: string }) {
  const theme = useTheme()
  return (
    <section aria-labelledby={id} className="rounded-2xl p-4 flex flex-col gap-1 min-w-0"
      style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.border}` }}>
      <h2 id={id} className="text-[12px] font-medium uppercase tracking-wide" style={{ color: theme.colors.textSub }}>{label}</h2>
      {children}
    </section>
  )
})

// ── summary cards ────────────────────────────────────────────

const SummaryCards = memo(function SummaryCards({ data, td, locale }: { data: DividendCalendarResponse; td: TD; locale: string }) {
  const theme = useTheme()
  const s = data.summary
  const inc = s.income_next_12m
  const np = s.next_payment
  const nextAmount = np
    ? np.expected_cash !== null ? money(np.expected_cash, np.currency, locale)
      : fill(td.cards.perShareOnly, { amount: perShare(np.amount_per_share, np.currency, locale) })
    : null
  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 min-w-0">
      <Card id="div-card-12m" label={td.cards.next12m}>
        <p className="text-[24px] font-bold tabular-nums leading-tight" style={{ color: theme.colors.text }}>
          {money(inc.total_cad, 'CAD', locale)}
        </p>
        <p className="text-[12px] tabular-nums break-words" style={{ color: theme.colors.textSub }}>{splitText(inc, locale)}</p>
        <p className="text-[11.5px]" style={{ color: theme.colors.textHint }}>{td.cards.next12mHelp}</p>
        {inc.fx_missing && <p className="text-[11.5px]" style={{ color: theme.colors.warning }}>{td.cards.fxMissing}</p>}
      </Card>
      <Card id="div-card-next" label={td.cards.nextPayment}>
        {np ? (
          <>
            <p className="text-[24px] font-bold tabular-nums leading-tight" style={{ color: theme.colors.text }}>{nextAmount}</p>
            <p className="text-[13px]" style={{ color: theme.colors.textSub }}>
              <Link href={`/stocks/${encodeURIComponent(np.symbol)}`} className="font-semibold underline-offset-2 hover:underline"
                style={{ color: theme.colors.primary }} aria-label={fill(td.agenda.openStock, { symbol: np.symbol })}>
                {np.symbol}
              </Link>
              {' · '}{shortDate(np.date, locale, true)}
            </p>
            {(np.estimated || np.pay_date_estimated) && (
              <div><Tag label={td.tags.estimated} title={td.tags.estimatedHelp} color={theme.colors.textSub} /></div>
            )}
          </>
        ) : (
          <p className="text-[15px]" style={{ color: theme.colors.textSub }}>{td.cards.nextPaymentNone}</p>
        )}
      </Card>
      <Card id="div-card-payers" label={td.cards.payers}>
        <p className="text-[24px] font-bold tabular-nums leading-tight" style={{ color: theme.colors.text }}>
          {fill(td.cards.payersValue, { n: s.payers, total: s.holdings })}
        </p>
        <p className="text-[12px] tabular-nums" style={{ color: theme.colors.textSub }}>
          {fill(td.cards.yearly, { amount: money(s.annual_income.total_cad, 'CAD', locale) })}
        </p>
        {s.forward_yield_pct !== null && (
          <p className="text-[12px] tabular-nums" style={{ color: theme.colors.textSub }}>
            {fill(td.cards.yield, { pct: `${num(s.forward_yield_pct, locale, 2)}%` })}
          </p>
        )}
      </Card>
    </div>
  )
})

// ── bar chart (plain divs, to scale) ─────────────────────────

const MonthBars = memo(function MonthBars({ months, td, locale }: { months: DividendMonth[]; td: TD; locale: string }) {
  const theme = useTheme()
  const bars = useMemo(() => months.map((m) => ({ key: m.month, value: m.total.total_cad ?? 0 })), [months])
  const max = useMemo(() => Math.max(0, ...bars.map((b) => b.value)), [bars])
  return (
    <section aria-labelledby="div-chart" className="rounded-2xl p-4 min-w-0"
      style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.border}` }}>
      <h2 id="div-chart" className="text-[15px] font-semibold mb-3" style={{ color: theme.colors.text }}>{td.chart.title}</h2>
      {max <= 0 ? (
        <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{td.chart.noData}</p>
      ) : (
        <ol aria-label={td.chart.aria} className="flex items-end gap-1 sm:gap-2 h-40 min-w-0">
          {bars.map((b) => {
            const label = fill(td.chart.bar, { month: monthLabel(b.key, locale), amount: money(b.value, 'CAD', locale) })
            const h = max > 0 ? (b.value / max) * 100 : 0
            return (
              <li key={b.key} aria-label={label} title={label} className="flex-1 min-w-0 h-full flex flex-col items-center justify-end gap-1">
                <div className="w-full flex-1 flex items-end">
                  <div className="w-full rounded-t-[4px]"
                    style={{ height: `${h}%`, minHeight: b.value > 0 ? 2 : 0, backgroundColor: theme.colors.primary }} />
                </div>
                <span aria-hidden="true" className="text-[10px] truncate max-w-full" style={{ color: theme.colors.textSub }}>
                  {monthLabel(b.key, locale, true)}
                </span>
              </li>
            )
          })}
        </ol>
      )}
    </section>
  )
})

// ── agenda ───────────────────────────────────────────────────

const EventRow = memo(function EventRow({ ev, td, locale }: { ev: DividendEvent; td: TD; locale: string }) {
  const theme = useTheme()
  const d = new Date(`${ev.date}T12:00:00Z`)
  const day = Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString(intl(locale), { day: 'numeric', timeZone: 'UTC' })
  const wd = Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString(intl(locale), { weekday: 'short', timeZone: 'UTC' })
  const muted = !ev.owned
  return (
    <li className="flex gap-3 py-3 min-w-0" style={{ borderTop: `1px solid ${theme.colors.border}` }}>
      <div className="w-10 shrink-0 flex flex-col items-center leading-tight" aria-hidden="true">
        <span className="text-[18px] font-bold tabular-nums" style={{ color: muted ? theme.colors.textSub : theme.colors.text }}>{day}</span>
        <span className="text-[10.5px] uppercase" style={{ color: theme.colors.textSub }}>{wd}</span>
      </div>
      <div className="flex-1 min-w-0 flex flex-col gap-1">
        <div className="flex items-baseline justify-between gap-2 min-w-0">
          <p className="min-w-0 truncate text-[14px]">
            <Link href={`/stocks/${encodeURIComponent(ev.symbol)}`} className="font-semibold underline-offset-2 hover:underline"
              style={{ color: muted ? theme.colors.textSub : theme.colors.text }}
              aria-label={fill(td.agenda.openStock, { symbol: ev.symbol })}>
              {ev.symbol}
            </Link>
            {ev.name && ev.name !== ev.symbol && (
              <span className="ml-2 text-[12px]" style={{ color: theme.colors.textHint }}>{ev.name}</span>
            )}
          </p>
          <span className="shrink-0 text-[14px] font-semibold tabular-nums"
            style={{ color: ev.expected_cash !== null ? theme.colors.up : theme.colors.textHint }}>
            {ev.expected_cash !== null ? money(ev.expected_cash, ev.currency, locale)
              : ev.owned ? (
                <Link href="/holdings" className="text-[12px] font-medium underline underline-offset-2"
                  style={{ color: theme.colors.primary }} aria-label={td.agenda.addSharesHelp} title={td.agenda.addSharesHelp}>
                  {td.agenda.addShares}
                </Link>
              ) : DASH}
          </span>
        </div>
        <p className="text-[12px] tabular-nums flex flex-wrap gap-x-2" style={{ color: theme.colors.textSub }}>
          <span>{fill(td.agenda.ex, { date: shortDate(ev.ex_date, locale) })}</span>
          <span>{ev.pay_date ? fill(td.agenda.pays, { date: shortDate(ev.pay_date, locale) }) : td.agenda.paysUnknown}</span>
          <span>{fill(td.agenda.perShare, { amount: perShare(ev.amount_per_share, ev.currency, locale) })}</span>
        </p>
        {(ev.estimated || ev.special || !ev.owned || ev.ex_passed || (ev.pay_date && ev.pay_date_estimated)) && (
          <div className="flex flex-wrap gap-1.5">
            {!ev.owned && <Tag label={td.tags.watchlist} title={td.tags.watchlistHelp} color={theme.colors.textSub} />}
            {ev.special && <Tag label={td.tags.special} title={td.tags.specialHelp} color={theme.colors.accent} />}
            {ev.ex_passed && <Tag label={td.tags.exPassed} title={td.tags.exPassedHelp} color={theme.colors.up} />}
            {ev.estimated ? <Tag label={td.tags.estimated} title={td.tags.estimatedHelp} color={theme.colors.warning} />
              : ev.pay_date && ev.pay_date_estimated
                ? <Tag label={td.tags.payEstimated} title={td.tags.estimatedHelp} color={theme.colors.warning} /> : null}
          </div>
        )}
      </div>
    </li>
  )
})

const MonthSection = memo(function MonthSection({ month, td, locale }: { month: DividendMonth; td: TD; locale: string }) {
  const theme = useTheme()
  const id = `div-month-${month.month}`
  const hasTotal = Object.keys(month.total.by_currency).length > 0
  return (
    <section aria-labelledby={id} className="rounded-2xl px-4 pt-3 pb-1 min-w-0"
      style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.border}` }}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 pb-2">
        <h3 id={id} className="text-[15px] font-semibold capitalize" style={{ color: theme.colors.text }}>
          {monthLabel(month.month, locale)}
        </h3>
        {hasTotal && (
          <span className="text-[12.5px] tabular-nums" style={{ color: theme.colors.textSub }}>
            {fill(td.agenda.monthTotal, { amount: splitText(month.total, locale) })}
          </span>
        )}
      </div>
      <ul>
        {month.events.map((ev) => (
          <EventRow key={`${ev.symbol}-${ev.ex_date}`} ev={ev} td={td} locale={locale} />
        ))}
      </ul>
    </section>
  )
})

// ── page ─────────────────────────────────────────────────────

export default function DividendCalendarPage() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const td = t.dividendsPage
  const [withWatchlist, setWithWatchlist] = useState(false)
  const q = useDividendCalendar(12, withWatchlist)
  const data = q.data
  const toggle = useCallback(() => setWithWatchlist((v) => !v), [])

  const monthsWithEvents = useMemo(() => (data?.months ?? []).filter((m) => m.events.length > 0), [data])
  const error = q.error && !data ? toHoldingsError(q.error) : null
  const errorMsg = error ? (td.errors as Record<string, string>)[error.code] ?? td.errors.internal : null
  const empty = !!data && data.summary.holdings === 0

  return (
    <div className="space-y-5 pb-4 min-w-0">
      <Link href="/dividends" aria-label={t.divSummary.backToDividends}
        className="-ml-2 min-h-[44px] px-2 inline-flex items-center gap-1.5 rounded-lg text-[13px] font-medium focus-visible:outline focus-visible:outline-2"
        style={{ color: theme.colors.textSub, outlineColor: theme.colors.primary }}>
        <ArrowLeft size={16} aria-hidden="true" />{t.divSummary.backToDividends}
      </Link>
      <header className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between min-w-0">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold flex items-center gap-2" style={{ color: theme.colors.text }}>
            <CalendarDays size={22} aria-hidden="true" style={{ color: theme.colors.primary }} />
            {td.title}
          </h1>
          <p className="text-[13px] md:text-sm mt-1 max-w-2xl" style={{ color: theme.colors.textSub }}>{td.subtitle}</p>
        </div>
        {!empty && (
          <button type="button" role="switch" aria-checked={withWatchlist} onClick={toggle}
            aria-label={td.includeWatchlist} title={td.includeWatchlistHelp}
            className="min-h-[44px] self-start md:self-auto px-3 rounded-xl text-[14px] font-medium flex items-center gap-2 focus-visible:outline focus-visible:outline-2"
            style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.text, outlineColor: theme.colors.primary }}>
            <span aria-hidden="true" className="relative inline-block w-9 h-5 rounded-full transition-colors"
              style={{ backgroundColor: withWatchlist ? theme.colors.primary : theme.colors.border }}>
              <span className="absolute top-0.5 w-4 h-4 rounded-full transition-all"
                style={{ left: withWatchlist ? 18 : 2, backgroundColor: theme.colors.surface }} />
            </span>
            {td.includeWatchlist}
          </button>
        )}
      </header>

      {q.isLoading && (
        <div className="space-y-3" aria-busy="true">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <Skeleton height={112} width="100%" />
            <Skeleton height={112} width="100%" />
            <Skeleton height={112} width="100%" />
          </div>
          <Skeleton height={200} width="100%" />
          <Skeleton height={160} width="100%" />
        </div>
      )}

      {errorMsg && (
        <div role="alert" className="rounded-2xl p-4 text-[14px] flex flex-wrap items-center justify-between gap-3"
          style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.down}`, color: theme.colors.text }}>
          <span>{errorMsg}</span>
          <button type="button" onClick={() => q.refetch()} aria-label={td.errors.retry}
            className="min-h-[44px] px-4 rounded-xl text-[14px] font-medium focus-visible:outline focus-visible:outline-2"
            style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.text, outlineColor: theme.colors.primary }}>
            {td.errors.retry}
          </button>
        </div>
      )}

      {empty && (
        <section className="rounded-2xl p-5 flex flex-col items-start gap-3" aria-labelledby="div-empty"
          style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.border}` }}>
          <h2 id="div-empty" className="text-[17px] font-semibold" style={{ color: theme.colors.text }}>{td.empty.title}</h2>
          <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{td.empty.body}</p>
          <Link href="/holdings" aria-label={td.empty.cta}
            className="min-h-[44px] px-4 rounded-xl text-[14px] font-semibold inline-flex items-center focus-visible:outline focus-visible:outline-2"
            style={{ backgroundColor: theme.colors.primary, color: theme.colors.surface, outlineColor: theme.colors.primary }}>
            {td.empty.cta}
          </Link>
        </section>
      )}

      {data && !empty && (
        <div className="space-y-5 min-w-0" aria-busy={q.isFetching}>
          {q.isFetching && !q.isLoading && (
            <p className="text-[12px]" style={{ color: theme.colors.textHint }} aria-live="polite">{td.refreshing}</p>
          )}
          <SummaryCards data={data} td={td} locale={locale} />

          {(data.missing_shares.length > 0 || data.non_payers.length > 0 || data.unknown.length > 0) && (
            <div className="rounded-2xl p-4 flex flex-col gap-1.5 text-[13px] min-w-0"
              style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.textSub }}>
              {data.missing_shares.length > 0 && (
                <p className="break-words">
                  {fill(td.notes.missingShares, { symbols: symbolsText(data.missing_shares) })}{' '}
                  <Link href="/holdings" className="font-medium underline underline-offset-2" style={{ color: theme.colors.primary }}
                    aria-label={td.notes.editHoldings}>
                    {td.notes.editHoldings}
                  </Link>
                </p>
              )}
              {data.non_payers.length > 0 && (
                <p className="break-words">
                  {fill(td.notes.nonPayers, {
                    symbols: data.non_payers.map((n) => {
                      const r = (td.reasons as Record<string, string>)[n.reason]
                      return r ? `${n.symbol} (${r})` : n.symbol
                    }).join(', '),
                  })}
                </p>
              )}
              {data.unknown.length > 0 && (
                <p className="break-words">{fill(td.notes.unknown, { symbols: symbolsText(data.unknown) })}</p>
              )}
            </div>
          )}

          <MonthBars months={data.months} td={td} locale={locale} />

          <section aria-labelledby="div-agenda" className="flex flex-col gap-3 min-w-0">
            <h2 id="div-agenda" className="text-[17px] font-semibold" style={{ color: theme.colors.text }}>{td.agenda.title}</h2>
            {monthsWithEvents.length === 0 ? (
              <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{td.agenda.none}</p>
            ) : (
              monthsWithEvents.map((m) => <MonthSection key={m.month} month={m} td={td} locale={locale} />)
            )}
          </section>

          <p className="text-[12px]" style={{ color: theme.colors.textHint }}>{td.notes.disclaimer}</p>
        </div>
      )}
    </div>
  )
}
