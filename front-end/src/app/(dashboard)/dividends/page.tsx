'use client'

import { Suspense, memo, useMemo, useState } from 'react'
import Link from 'next/link'
import { CalendarDays, ChevronRight, Receipt } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore, INTL_LOCALES } from '@/store/i18nStore'
import { useAccess } from '@/hooks/useAccess'
import { useProfile } from '@/hooks/useProfile'
import { useAllocation, useDividendSummary, useMoney, useScope } from '@/hooks/usePortfolioInsights'
import { DASH, fill, shortDate } from '@/lib/insights'
import { pct, spct } from '@/components/holdings/format'
import { HomeHeader } from '@/components/home/HomeHeader'
import { SectionCard, SoonBadge, useButtonStyles } from '@/components/profile/ui'
import { MonthlyBars } from '@/components/tracker/MonthlyBars'
import { Tag } from '@/components/tracker/EventRow'
import {
  ChipGroup, EmptyHoldings, Freshness, HideAmountsButton, QueryError, SafetyChip, ScopeSelect, SkeletonCards, Stat, useSignColor,
} from '@/components/tracker/ui'
import type en from '@/lib/i18n/en.json'
import type { DividendPayer, DividendSummary, UpcomingPayment } from '@/types/tracker'

type TD = typeof en['divSummary']

export default function DividendsPage() {
  return (
    <Suspense fallback={null}>
      <DividendsInner />
    </Suspense>
  )
}

function DividendsInner() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const td = t.divSummary
  const { can } = useAccess()
  const btn = useButtonStyles()
  const { scope, query, setScope, scoped } = useScope()
  const year = new Date().getFullYear()
  const [period, setPeriod] = useState('next12m')
  const q = useDividendSummary(scope, period)
  const d = q.data
  const profile = useProfile(can('area.profile'))
  // option-income payers → link to the income-quality page
  const alloc = useAllocation(scope, can('area.insights'))
  const optionIncome = useMemo(
    () => new Set((alloc.data?.tiles ?? []).filter((x) => x.class === 'option_income_etfs').map((x) => x.symbol)),
    [alloc.data],
  )
  const periods = useMemo(() => [
    { value: 'next12m', label: td.periods.next12m },
    { value: String(year), label: String(year) },
    { value: String(year - 1), label: String(year - 1) },
    { value: String(year - 2), label: String(year - 2) },
  ], [td, year])
  const empty = !!d && d.payers.length === 0 && d.non_payers.length === 0 && !d.market_value && !scoped

  return (
    <div className="space-y-4 pb-4 min-w-0">
      <HomeHeader title={td.title} actions={<HideAmountsButton />} />
      <ScopeSelect scope={scope} onChange={setScope} />
      <ChipGroup value={period} options={periods} onChange={setPeriod} label={td.periodLabel} />

      {q.isLoading && <SkeletonCards heights={[150, 180, 160]} />}
      {!!q.error && !d && <QueryError error={q.error} onRetry={() => q.refetch()} />}
      {empty && <EmptyHoldings body={td.emptyBody} />}

      {d && !empty && (
        <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_380px] gap-4 items-start min-w-0" aria-busy={q.isFetching}>
          <div className="flex flex-col gap-4 min-w-0">
            <Headline d={d} td={td} taxView={profile.data?.dividend_tax_view ?? 'before'} />
            <SectionCard title={td.monthsTitle} subtitle={d.kind === 'received' ? td.monthsReceived : td.monthsExpected}>
              <BarsWithMoney d={d} />
            </SectionCard>
            <IncomeChangeCard d={d} td={td} />
            <PayersCard d={d} td={td} optionIncome={optionIncome} canQuality={can('area.insights')} scopeQuery={query} />
          </div>
          <div className="flex flex-col gap-4 min-w-0">
            <UpcomingCard d={d} td={td} />
            <Link href="/dividends/calendar" className={btn.secondary.className} style={btn.secondary.style}>
              <CalendarDays size={16} aria-hidden="true" />{td.fullCalendar}
            </Link>
            <Freshness asOf={d.as_of} delayed={d.delayed_minutes} />
            <p className="text-[12px]" style={{ color: theme.colors.textHint }}>{t.dividendsPage.notes.disclaimer}</p>
          </div>
        </div>
      )}
    </div>
  )
}

function BarsWithMoney({ d }: { d: DividendSummary }) {
  const { fmt } = useMoney(d.currency)
  return <MonthlyBars months={d.months} fmt={(v) => fmt(v)} />
}

function Headline({ d, td, taxView }: { d: DividendSummary; td: TD; taxView: 'before' | 'after' }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const { fmt } = useMoney(d.currency)
  const signColor = useSignColor()
  const afterTax = d.tax !== null && d.after_tax_total !== null && d.kind === 'expected'
  const total = afterTax ? d.after_tax_total ?? d.total : d.total
  const withheld = d.tax ? d.tax.lost + d.tax.recoverable : 0
  const title = d.kind === 'received' ? fill(td.receivedIn, { year: d.period }) : td.expected12m
  const taxLabel = afterTax || (d.kind === 'expected' && taxView === 'after' && d.tax) ? td.afterTax : td.beforeTax
  return (
    <section aria-labelledby="div-head" className="rounded-2xl p-4 md:p-5 flex flex-col gap-3 min-w-0"
      style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.border}` }}>
      <div className="min-w-0">
        <h2 id="div-head" className="text-[13px] font-medium" style={{ color: theme.colors.textSub }}>
          {title} · <span>{d.kind === 'received' ? td.asRecorded : taxLabel}</span>
        </h2>
        <p className="text-[30px] font-bold tabular-nums leading-tight" style={{ color: theme.colors.text }}>{fmt(total)}</p>
        <p className="text-[13px] tabular-nums" style={{ color: theme.colors.textSub }}>
          {fill(td.perMonthDay, { month: fmt(total / 12), day: fmt(total / 365) })}
        </p>
        {d.kind === 'received' && (
          <p className="text-[12px] mt-1" style={{ color: theme.colors.textHint }}>
            {fill(td.forwardNote, { amount: fmt(d.forward_income) })}
          </p>
        )}
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <Stat label={td.stats.yield} value={pct(d.yield_pct, 2)} />
        <Stat label={td.stats.onCost} value={pct(d.yield_on_cost_pct, 2)} />
        <Stat label={td.stats.growth5y} value={spct(d.growth.growth_5y_pct, 1)} color={signColor(d.growth.growth_5y_pct)}
          sub={d.growth.coverage_5y_pct != null ? fill(td.stats.coverage, { pct: pct(d.growth.coverage_5y_pct, 0) }) : undefined} />
        <Stat label={td.stats.growth1y} value={spct(d.growth.growth_1y_pct, 1)} color={signColor(d.growth.growth_1y_pct)}
          sub={d.growth.coverage_1y_pct != null ? fill(td.stats.coverage, { pct: pct(d.growth.coverage_1y_pct, 0) }) : undefined} />
      </div>
      {d.tax && (
        <Link href="/dividends/tax" aria-label={td.tax.open}
          className="flex items-center gap-2 rounded-xl px-3 py-2.5 min-h-[44px] focus-visible:outline focus-visible:outline-2"
          style={{ backgroundColor: theme.colors.surfaceAlt, outlineColor: theme.colors.primary }}>
          <Receipt size={16} aria-hidden="true" style={{ color: theme.colors.primary }} />
          <span className="flex-1 min-w-0 text-[13px]" style={{ color: theme.colors.text }}>
            {fill(td.tax.withheldLine, { amount: fmt(withheld), gross: fmt(d.tax.gross_total) })}
          </span>
          <SoonBadge label={t.tracker.premium} tone="primary" />
          <ChevronRight size={16} aria-hidden="true" style={{ color: theme.colors.textSub }} />
        </Link>
      )}
      {(d.notes ?? []).includes('no_dividend_transactions') && (
        <p className="text-[12.5px]" style={{ color: theme.colors.textSub }}>
          {td.noTransactions}{' '}
          <Link href="/profile/transactions" className="underline underline-offset-2 font-medium" style={{ color: theme.colors.primary }}>
            {td.addTransactions}
          </Link>
        </p>
      )}
      {d.unconverted.length > 0 && (
        <p className="text-[12px]" style={{ color: theme.colors.warning }}>{fill(td.unconverted, { symbols: d.unconverted.join(', ') })}</p>
      )}
    </section>
  )
}

const UpcomingRow = memo(function UpcomingRow({ u, currency, td }: { u: UpcomingPayment; currency: string; td: TD }) {
  const theme = useTheme()
  const locale = useI18nStore((s) => s.locale)
  const { fmt } = useMoney(currency)
  const date = u.pay_date ?? u.ex_date
  return (
    <li className="flex items-start justify-between gap-3 py-2.5 min-w-0" style={{ borderTop: `1px solid ${theme.colors.border}` }}>
      <div className="min-w-0">
        <Link href={`/stocks/${encodeURIComponent(u.symbol)}`} className="text-[14px] font-semibold underline-offset-2 hover:underline"
          style={{ color: theme.colors.text }}>{u.symbol}</Link>
        <p className="text-[12px] tabular-nums" style={{ color: theme.colors.textSub }}>
          {u.pay_date ? fill(td.upcoming.pays, { date: shortDate(u.pay_date, locale) }) : fill(td.upcoming.ex, { date: shortDate(u.ex_date, locale) })}
          {u.account_name ? ` · ${u.account_name}` : ''}
        </p>
        {(u.estimated || u.pay_date_estimated || u.ex_passed) && (
          <div className="flex flex-wrap gap-1.5 mt-1">
            {(u.estimated || u.pay_date_estimated) && <Tag label={td.upcoming.estimated} title={td.upcoming.estimatedHelp} color={theme.colors.warning} />}
            {u.ex_passed && <Tag label={td.upcoming.locked} title={td.upcoming.lockedHelp} color={theme.colors.up} />}
          </div>
        )}
      </div>
      <div className="text-right shrink-0">
        <p className="text-[14px] font-semibold tabular-nums" style={{ color: u.cash != null ? theme.colors.up : theme.colors.textHint }}>
          {u.cash != null ? fmt(u.after_tax ?? u.cash) : DASH}
        </p>
        {date && <p className="sr-only">{shortDate(date, locale)}</p>}
      </div>
    </li>
  )
})

function UpcomingCard({ d, td }: { d: DividendSummary; td: TD }) {
  const theme = useTheme()
  return (
    <SectionCard title={td.upcoming.title} subtitle={td.upcoming.subtitle}>
      {d.upcoming.length === 0 ? (
        <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{td.upcoming.none}</p>
      ) : (
        <ul className="-mt-2">
          {d.upcoming.map((u, i) => <UpcomingRow key={`${u.symbol}-${u.account_id}-${u.ex_date}-${i}`} u={u} currency={d.currency} td={td} />)}
        </ul>
      )}
    </SectionCard>
  )
}

function IncomeChangeCard({ d, td }: { d: DividendSummary; td: TD }) {
  const theme = useTheme()
  const locale = useI18nStore((s) => s.locale)
  const { fmt, signed } = useMoney(d.currency)
  const signColor = useSignColor()
  const ic = d.income_change
  const tc = td.change
  const rows = useMemo(() => {
    const c = ic?.components
    if (!c) return []
    return ([
      ['raises', c.raises], ['cuts', c.cuts], ['new_shares', c.new_shares], ['removed_shares', c.removed_shares], ['fx', c.fx],
    ] as const).filter(([, v]) => Math.abs(v) >= 0.005)
  }, [ic])
  const items = useMemo(() => (ic?.items ?? []).slice().sort((a, b) => Math.abs(b.amount) - Math.abs(a.amount)).slice(0, 6), [ic])
  let body: React.ReactNode
  if (!ic || ic.reason === 'migration_required') {
    body = <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{tc.unavailable}</p>
  } else if (ic.reason === 'whole_portfolio_only') {
    body = <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{tc.wholeOnly}</p>
  } else if (!ic.components) {
    body = (
      <p className="text-[13px]" style={{ color: theme.colors.textSub }}>
        {ic.available_from ? fill(tc.availableFrom, { date: shortDate(ic.available_from, locale, true) }) : tc.unavailable}
      </p>
    )
  } else {
    body = (
      <div className="flex flex-col gap-2">
        <p className="text-[14px] tabular-nums" style={{ color: theme.colors.text }}>
          {fmt(ic.before_total)} → {fmt(ic.now_total)}{' '}
          <span className="font-semibold" style={{ color: signColor(ic.change) }}>({signed(ic.change)})</span>
        </p>
        {!ic.full_period && ic.from_date && (
          <p className="text-[12px]" style={{ color: theme.colors.textHint }}>{fill(tc.partial, { date: shortDate(ic.from_date, locale, true) })}</p>
        )}
        {rows.length === 0 ? (
          <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{tc.noChange}</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {rows.map(([k, v]) => (
              <li key={k} className="flex items-center justify-between gap-2 text-[13px]">
                <span style={{ color: theme.colors.textSub }}>{(tc.components as Record<string, string>)[k]}</span>
                <span className="tabular-nums font-medium" style={{ color: signColor(v) }}>{signed(v)}</span>
              </li>
            ))}
          </ul>
        )}
        {items.length > 0 && (
          <ul className="flex flex-col gap-1 pt-2" style={{ borderTop: `1px solid ${theme.colors.border}` }}>
            {items.map((it) => (
              <li key={`${it.symbol}-${it.kind}`} className="flex items-center justify-between gap-2 text-[12.5px]">
                <span style={{ color: theme.colors.text }}>
                  <span className="font-semibold">{it.symbol}</span>{' '}
                  <span style={{ color: theme.colors.textSub }}>{(tc.kinds as Record<string, string>)[it.kind] ?? it.kind}</span>
                </span>
                <span className="tabular-nums" style={{ color: signColor(it.amount) }}>{signed(it.amount)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    )
  }
  return <SectionCard title={tc.title} subtitle={ic?.components ? fill(tc.subtitle, { days: ic.days }) : undefined}>{body}</SectionCard>
}

const MONTH_KEYS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]

const PayerRow = memo(function PayerRow({ p, currency, td, quality, kind }: {
  p: DividendPayer
  currency: string
  td: TD
  quality: string | null
  kind: 'expected' | 'received'
}) {
  const theme = useTheme()
  const locale = useI18nStore((s) => s.locale)
  const { fmt } = useMoney(currency)
  const monthNames = useMemo(() => MONTH_KEYS.map((m) =>
    new Date(Date.UTC(2026, m, 15)).toLocaleDateString(INTL_LOCALES[locale], { month: 'short', timeZone: 'UTC' })), [locale])
  const paid = p.months.map((on, i) => (on ? monthNames[i] : null)).filter(Boolean).join(', ')
  const amount = kind === 'received' ? p.period_amount : p.annual_amount
  return (
    <li className="py-3 flex flex-col gap-1.5 min-w-0" style={{ borderTop: `1px solid ${theme.colors.border}` }}>
      <div className="flex items-center justify-between gap-2 min-w-0">
        <div className="flex items-center gap-2 min-w-0">
          <Link href={`/stocks/${encodeURIComponent(p.symbol)}`} className="text-[14px] font-semibold underline-offset-2 hover:underline truncate"
            style={{ color: theme.colors.text }}>{p.symbol}</Link>
          <SafetyChip grade={p.safety} />
        </div>
        <span className="text-[14px] font-semibold tabular-nums shrink-0" style={{ color: theme.colors.text }}>{fmt(amount)}</span>
      </div>
      <div className="flex items-center justify-between gap-2 min-w-0">
        <ol aria-label={fill(td.payers.monthsAria, { months: paid || DASH })} className="flex gap-[3px]">
          {p.months.map((on, i) => (
            <li key={i} aria-hidden="true" title={monthNames[i]} className="w-2 h-2 rounded-full"
              style={{ backgroundColor: on ? theme.colors.primary : theme.colors.surfaceAlt, border: on ? 'none' : `1px solid ${theme.colors.border}` }} />
          ))}
        </ol>
        <span className="text-[12px] tabular-nums" style={{ color: theme.colors.textSub }}>
          {fill(td.payers.line, { share: pct(p.share_pct, 0), yield: pct(p.yield_pct, 2) })}
        </span>
      </div>
      {((td.payers.details as Record<string, string>)[p.detail] || quality) && (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-[12px]" style={{ color: theme.colors.textHint }}>{(td.payers.details as Record<string, string>)[p.detail] ?? ''}</span>
          {quality && (
            <Link href={quality} className="text-[12.5px] font-medium min-h-[44px] inline-flex items-center gap-0.5 focus-visible:outline focus-visible:outline-2 rounded"
              aria-label={fill(td.payers.qualityAria, { symbol: p.symbol })}
              style={{ color: theme.colors.primary, outlineColor: theme.colors.primary }}>
              {td.payers.quality}<ChevronRight size={14} aria-hidden="true" />
            </Link>
          )}
        </div>
      )}
    </li>
  )
})

function PayersCard({ d, td, optionIncome, canQuality, scopeQuery }: {
  d: DividendSummary
  td: TD
  optionIncome: Set<string>
  canQuality: boolean
  scopeQuery: string
}) {
  const theme = useTheme()
  return (
    <SectionCard title={td.payers.title} subtitle={fill(td.payers.subtitle, { n: d.payers.length })}>
      {d.payers.length === 0 ? (
        <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{td.payers.none}</p>
      ) : (
        <ul className="-mt-2">
          {d.payers.map((p) => (
            <PayerRow key={p.symbol} p={p} currency={d.currency} td={td} kind={d.kind}
              quality={canQuality && optionIncome.has(p.symbol) ? `/insights/income/${encodeURIComponent(p.symbol)}${scopeQuery}` : null} />
          ))}
        </ul>
      )}
      {d.non_payers.length > 0 && (
        <p className="text-[12px]" style={{ color: theme.colors.textHint }}>{fill(td.payers.nonPayers, { symbols: d.non_payers.join(', ') })}</p>
      )}
    </SectionCard>
  )
}
