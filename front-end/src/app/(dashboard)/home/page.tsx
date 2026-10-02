'use client'

import { Suspense, memo, useMemo } from 'react'
import Link from 'next/link'
import { useCardLink } from '@/hooks/useCardLink'
import { AlertTriangle, Bell, CalendarCheck, ChevronRight, Info } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useAccess } from '@/hooks/useAccess'
import { useProfile } from '@/hooks/useProfile'
import {
  useAllocation, useDividendSummary, useMoney, usePortfolioSummary, useScope, useUpcomingEvents,
} from '@/hooks/usePortfolioInsights'
import { fill, shortDate } from '@/lib/insights'
import { pct } from '@/components/holdings/format'
import { HomeHeader } from '@/components/home/HomeHeader'
import { HomeValueCard } from '@/components/tracker/PortfolioValueCard'
import { EventRow } from '@/components/tracker/EventRow'
import { EmptyHoldings, HideAmountsButton, QueryError, ScopeSelect, SkeletonCards } from '@/components/tracker/ui'
import { warningText } from '@/components/tracker/text'
import type { DividendSummary, EventItem } from '@/types/tracker'

export default function HomePage() {
  return (
    <Suspense fallback={null}>
      <HomeInner />
    </Suspense>
  )
}

function HomeInner() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const { can } = useAccess()
  const { scope, query, setScope, scoped } = useScope()
  const profile = useProfile(can('area.profile'))
  const name = profile.data?.display_name?.trim()
  const greeting = name ? fill(t.home.hello, { name }) : t.home.helloAnon
  const summary = usePortfolioSummary(scope, can('area.home'))
  const s = summary.data
  const empty = !!s && s.holdings_count === 0 && !scoped
  const ready = !!s && !empty

  return (
    <div className="space-y-4 pb-4 min-w-0">
      <HomeHeader title={t.home.title} greeting={greeting}
        actions={<>{can('area.coming_up') && <ComingUpBell scopeQuery={query} />}<HideAmountsButton /></>} />
      {can('area.coming_up') && <DividendsTodayPill scopeQuery={query} />}
      <ScopeSelect scope={scope} onChange={setScope} />

      {summary.isLoading && <SkeletonCards heights={[150, 140, 120]} />}
      {!!summary.error && !s && <QueryError error={summary.error} onRetry={() => summary.refetch()} />}
      {empty && <EmptyHoldings />}

      {ready && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start min-w-0">
          <div className="flex flex-col gap-4 min-w-0">
            <HomeValueCard summary={s} href={`/holdings${query}`} />
            {can('area.dividends') && <DividendsCard scopeQuery={query} />}
          </div>
          <div className="flex flex-col gap-4 min-w-0">
            <WorthALook />
            {can('area.coming_up') && <ComingUpCard scopeQuery={query} currency={s.currency} />}
          </div>
        </div>
      )}
      <p className="text-[12px]" style={{ color: theme.colors.textHint }}>{t.tracker.notAdvice}</p>
    </div>
  )
}

function Card({ id, title, right, children, href }: { id: string; title: string; right?: React.ReactNode; children: React.ReactNode; href?: string }) {
  const theme = useTheme()
  const cardLink = useCardLink(href)
  return (
    <section aria-labelledby={id} onClick={cardLink.onClick} className={`rounded-2xl p-4 md:p-5 flex flex-col gap-3 min-w-0 ${href ? 'hover:brightness-110' : ''} ${cardLink.className}`}
      style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.border}` }}>
      <div className="flex items-center justify-between gap-2 min-w-0">
        <h2 id={id} className="text-[15px] font-semibold" style={{ color: theme.colors.text }}>{title}</h2>
        {right}
      </div>
      {children}
    </section>
  )
}

function MoreLink({ href, label, aria }: { href: string; label: string; aria?: string }) {
  const theme = useTheme()
  return (
    <Link href={href} aria-label={aria ?? label}
      className="text-[13px] font-medium min-h-[44px] inline-flex items-center gap-0.5 px-1 rounded focus-visible:outline focus-visible:outline-2"
      style={{ color: theme.colors.primary, outlineColor: theme.colors.primary }}>
      {label}<ChevronRight size={14} aria-hidden="true" />
    </Link>
  )
}

/** Steady vs option/variable income split bar. */
const SplitBar = memo(function SplitBar({ steady, variable }: { steady: number; variable: number }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const total = steady + variable
  if (total <= 0) return null
  const sp = (steady / total) * 100
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex h-2.5 rounded-full overflow-hidden" role="img"
        aria-label={fill(t.home.splitAria, { steady: pct(sp, 0), variable: pct(100 - sp, 0) })}
        style={{ backgroundColor: theme.colors.surfaceAlt }}>
        <div style={{ width: `${sp}%`, backgroundColor: theme.colors.primary }} />
        <div style={{ width: `${100 - sp}%`, backgroundColor: theme.colors.warning }} />
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-[12px]" style={{ color: theme.colors.textSub }}>
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden="true" className="w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: theme.colors.primary }} />
          {fill(t.home.steadyShare, { pct: pct(sp, 0) })}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden="true" className="w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: theme.colors.warning }} />
          {fill(t.home.variableShare, { pct: pct(100 - sp, 0) })}
        </span>
      </div>
    </div>
  )
})

function DividendsCard({ scopeQuery }: { scopeQuery: string }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const { scope } = useScope()
  const q = useDividendSummary(scope, 'next12m')
  const d = q.data
  const { fmt } = useMoney(d?.currency)
  const annual = d ? d.after_tax_total ?? d.forward_income : 0
  return (
    <Card id="home-div" href={`/dividends${scopeQuery}`} title={t.home.dividendsTitle} right={<MoreLink href={`/dividends${scopeQuery}`} label={t.home.seeDividends} />}>
      {q.isLoading && <div className="h-24 rounded-xl animate-pulse" style={{ backgroundColor: theme.colors.surfaceAlt }} />}
      {!!q.error && !d && <QueryError error={q.error} onRetry={() => q.refetch()} />}
      {d && (
        d.forward_income <= 0 ? (
          <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{t.home.noDividends}</p>
        ) : (
          <>
            <div>
              <p className="text-[24px] font-bold tabular-nums leading-tight" style={{ color: theme.colors.text }}>{fmt(annual)}</p>
              <p className="text-[12.5px]" style={{ color: theme.colors.textSub }}>
                {d.after_tax_total !== null ? t.home.next12mAfterTax : t.home.next12m}
              </p>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div className="rounded-xl p-2.5" style={{ backgroundColor: theme.colors.surfaceAlt }}>
                <p className="text-[16px] font-semibold tabular-nums" style={{ color: theme.colors.text }}>{fmt(annual / 12)}</p>
                <p className="text-[12px]" style={{ color: theme.colors.textSub }}>{t.home.perMonth}</p>
              </div>
              <div className="rounded-xl p-2.5" style={{ backgroundColor: theme.colors.surfaceAlt }}>
                <p className="text-[16px] font-semibold tabular-nums" style={{ color: theme.colors.text }}>{fmt(annual / 365)}</p>
                <p className="text-[12px]" style={{ color: theme.colors.textSub }}>{t.home.perDay}</p>
              </div>
            </div>
            <SplitBar steady={d.steady_total} variable={d.variable_total} />
          </>
        )
      )}
    </Card>
  )
}

interface Tip { key: string; text: string; href?: string; tone: 'warning' | 'info' }

function taxTip(d: DividendSummary | undefined, t: ReturnType<typeof useI18nStore.getState>['t'], fmt: (v: number) => string): Tip | null {
  const tax = d?.tax
  if (!tax) return null
  if (tax.lost > 0) return { key: 'tax', text: fill(t.home.tips.taxLost, { amount: fmt(tax.lost) }), href: '/dividends/tax', tone: 'info' }
  if (tax.untyped_accounts.length > 0) return { key: 'tax', text: t.home.tips.taxUntyped, href: '/profile/accounts', tone: 'info' }
  if (tax.recoverable > 0) return { key: 'tax', text: fill(t.home.tips.taxRecoverable, { amount: fmt(tax.recoverable) }), href: '/dividends/tax', tone: 'info' }
  return null
}

function WorthALook() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const { can } = useAccess()
  const { scope, query } = useScope()
  const alloc = useAllocation(scope, can('area.insights'))
  const div = useDividendSummary(scope, 'next12m', can('area.dividends'))
  const { fmt } = useMoney(div.data?.currency)
  const tips = useMemo<Tip[]>(() => {
    const out: Tip[] = []
    for (const w of alloc.data?.warnings ?? []) {
      out.push({ key: `w-${w.code}-${w.params.symbol ?? ''}`, text: warningText(w, t), href: `/holdings${query ? `${query}&` : '?'}tab=allocation`, tone: 'warning' })
    }
    for (const p of div.data?.payers ?? []) {
      if (p.safety === 'watch' || p.safety === 'cut') {
        const detail = (t.divSummary.payers.details as Record<string, string>)[p.detail] ?? ''
        out.push({
          key: `p-${p.symbol}`,
          text: fill(p.safety === 'cut' ? t.home.tips.payerCut : t.home.tips.payerWatch, { symbol: p.symbol, detail }),
          href: `/stocks/${encodeURIComponent(p.symbol)}`,
          tone: 'warning',
        })
      }
    }
    const tip = taxTip(div.data, t, (v) => fmt(v))
    if (tip) out.push(tip)
    return out
  }, [alloc.data, div.data, t, query, fmt])
  const loading = (can('area.insights') && alloc.isLoading) || (can('area.dividends') && div.isLoading)

  return (
    <Card id="home-look" title={t.home.worthALook}>
      {loading && tips.length === 0 ? (
        <div className="h-16 rounded-xl animate-pulse" style={{ backgroundColor: theme.colors.surfaceAlt }} />
      ) : tips.length === 0 ? (
        <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{t.home.allGood}</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {tips.map((tip) => <TipRow key={tip.key} tip={tip} />)}
        </ul>
      )}
    </Card>
  )
}

const TipRow = memo(function TipRow({ tip }: { tip: Tip }) {
  const theme = useTheme()
  const Icon = tip.tone === 'warning' ? AlertTriangle : Info
  const color = tip.tone === 'warning' ? theme.colors.warning : theme.colors.primary
  const body = (
    <>
      <Icon size={16} aria-hidden="true" className="shrink-0 mt-0.5" style={{ color }} />
      <span className="flex-1 min-w-0 text-[13px] break-words" style={{ color: theme.colors.text }}>{tip.text}</span>
      {tip.href && <ChevronRight size={16} aria-hidden="true" className="shrink-0 mt-0.5" style={{ color: theme.colors.textSub }} />}
    </>
  )
  const cls = 'flex items-start gap-2.5 rounded-xl px-3 py-2.5 min-h-[44px]'
  return (
    <li>
      {tip.href ? (
        <Link href={tip.href} aria-label={tip.text} className={`${cls} focus-visible:outline focus-visible:outline-2`}
          style={{ backgroundColor: theme.colors.surfaceAlt, outlineColor: theme.colors.primary }}>{body}</Link>
      ) : (
        <div className={cls} style={{ backgroundColor: theme.colors.surfaceAlt }}>{body}</div>
      )}
    </li>
  )
})

function ComingUpCard({ scopeQuery, currency }: { scopeQuery: string; currency: string }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const { scope } = useScope()
  const q = useUpcomingEvents(scope, 30)
  const items = useMemo(() => (q.data?.items ?? []).filter((e) => !e.recent).slice(0, 4), [q.data])
  return (
    <Card id="home-next" title={t.home.comingUp} right={<MoreLink href={`/coming-up${scopeQuery}`} label={t.home.seeAll} aria={t.home.seeAllComingUp} />}>
      {q.isLoading && <div className="h-24 rounded-xl animate-pulse" style={{ backgroundColor: theme.colors.surfaceAlt }} />}
      {!!q.error && !q.data && <QueryError error={q.error} onRetry={() => q.refetch()} />}
      {q.data && (items.length === 0 ? (
        <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{t.home.nothingSoon}</p>
      ) : (
        <ul className="-mt-3">
          {items.map((ev, i) => (
            <EventRow key={`${ev.type}-${ev.symbol}-${ev.date}-${i}`} ev={ev} currency={currency} showDate={shortDate(ev.date, locale)} />
          ))}
        </ul>
      ))}
    </Card>
  )
}


/** Today's events for stocks the user OWNS, and price alerts that fired today. */
function useToday() {
  const { scope } = useScope()
  const q = useUpcomingEvents(scope, 30)   // same query (and cache) as the Coming up card
  return useMemo(() => {
    const d = q.data
    if (!d) return { owned: [] as EventItem[], alerts: [] as EventItem[], currency: 'CAD' }
    const today = d.today
    return {
      owned: d.items.filter((e) => e.owned && e.date === today && !e.recent),
      alerts: d.items.filter((e) => e.type === 'price_alert' && e.date === today),
      currency: d.home_currency,
    }
  }, [q.data])
}

/** Bell in the Home header → Coming up; red dot when something of the
 *  user's happens today or one of their alerts just fired. */
function ComingUpBell({ scopeQuery }: { scopeQuery: string }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const { owned, alerts } = useToday()
  const dot = owned.length > 0 || alerts.length > 0
  const label = dot ? t.home.bellNew : t.home.bell
  return (
    <Link href={`/coming-up${scopeQuery}`} aria-label={label} title={label}
      className="relative min-h-[44px] min-w-[44px] rounded-full inline-flex items-center justify-center focus-visible:outline focus-visible:outline-2"
      style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.text, outlineColor: theme.colors.primary }}>
      <Bell size={18} aria-hidden="true" />
      {dot && <span aria-hidden="true" className="absolute top-2.5 right-2.5 w-2.5 h-2.5 rounded-full"
        style={{ backgroundColor: theme.colors.down, boxShadow: `0 0 0 2px ${theme.colors.surfaceAlt}` }} />}
    </Link>
  )
}

/** "AAPL.TO pays you C$42.18 today" — only on days with a dividend event
 *  for a stock the user owns. Opens Coming up. */
function DividendsTodayPill({ scopeQuery }: { scopeQuery: string }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const th = t.home.today
  const { owned, currency } = useToday()
  const { fmt } = useMoney(currency)
  const pays = owned.filter((e) => e.type === 'dividend_payment')
  const exs = owned.filter((e) => e.type === 'ex_dividend')
  let text: string | null = null
  if (pays.length === 1) {
    const e = pays[0]
    text = e.cash_home != null ? fill(th.paysOne, { symbol: e.symbol ?? '', amount: fmt(e.cash_home) }) : fill(th.paysOneNoCash, { symbol: e.symbol ?? '' })
  } else if (pays.length > 1) {
    const total = pays.reduce((a, e) => a + (e.cash_home ?? 0), 0)
    text = fill(th.paysMany, { n: pays.length, amount: fmt(total) })
  } else if (exs.length === 1) {
    text = fill(th.exOne, { symbol: exs[0].symbol ?? '' })
  } else if (exs.length > 1) {
    text = fill(th.exMany, { n: exs.length })
  }
  if (!text) return null
  return (
    <Link href={`/coming-up${scopeQuery}`}
      className="inline-flex items-center gap-2 rounded-full px-3.5 min-h-[40px] text-[13.5px] font-medium hover:brightness-110 focus-visible:outline focus-visible:outline-2"
      style={{ backgroundColor: theme.colors.up + '1f', color: theme.colors.up, outlineColor: theme.colors.primary }}>
      <CalendarCheck size={16} aria-hidden="true" />{text}<ChevronRight size={15} aria-hidden="true" />
    </Link>
  )
}
