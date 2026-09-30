'use client'

import { memo } from 'react'
import Link from 'next/link'
import { BarChart3, BellRing, CalendarCheck, Coins, Landmark, Megaphone, ShieldCheck, type LucideIcon } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useMoney } from '@/hooks/usePortfolioInsights'
import { DASH, fill, nativePrice, shortDate } from '@/lib/insights'
import { money, num } from '@/components/holdings/format'
import type en from '@/lib/i18n/en.json'
import type { EventItem, EventType } from '@/types/tracker'

type T = typeof en

const ICONS: Record<EventType, LucideIcon> = {
  ex_dividend: CalendarCheck,
  dividend_payment: Coins,
  earnings: Megaphone,
  analyst: BarChart3,
  check_changed: ShieldCheck,
  economy: Landmark,
  price_alert: BellRing,
}

function statusText(v: string, t: T): string {
  return (t.stock.statusLabel as Record<string, string>)[v] ?? v
}

function checkLabel(key: string, t: T): string {
  const c = (t.stock.checks as Record<string, { label?: string }>)[key]
  return c?.label ?? key.replace(/_/g, ' ')
}

/** Translated title + detail lines for one feed item (the API's own
 *  title/detail are English; they're used only as a last resort). */
export function eventText(ev: EventItem, t: T, locale: string, fmtHome: (v: number | null | undefined) => string, hidden: boolean): { title: string; lines: string[] } {
  const te = t.comingUpPage.events
  const sym = ev.symbol ?? ''
  const cash = ev.cash_home ?? null
  const cashNative = ev.cash !== null && ev.currency ? (hidden ? '••••' : money(ev.cash, ev.currency, locale)) : null
  const per = ev.amount_per_share != null && ev.currency ? money(ev.amount_per_share, ev.currency, locale, ev.amount_per_share < 1 ? 4 : 2) : null
  switch (ev.type) {
    case 'ex_dividend': {
      const lines: string[] = []
      if (per) lines.push(fill(te.perShare, { amount: per }))
      if (ev.shares && (cash !== null || cashNative)) lines.push(fill(te.forShares, { amount: cash !== null ? fmtHome(cash) : cashNative, shares: num(ev.shares, locale) }))
      if (ev.pay_date) lines.push(fill(te.paysOn, { date: shortDate(ev.pay_date, locale) }))
      return { title: fill(ev.special ? te.exDivSpecial : te.exDiv, { symbol: sym }), lines }
    }
    case 'dividend_payment': {
      const amt = cash !== null ? fmtHome(cash) : cashNative
      const lines: string[] = []
      if (per) lines.push(fill(te.perShare, { amount: per }))
      return { title: amt ? fill(te.payment, { symbol: sym, amount: amt }) : fill(te.paymentNoCash, { symbol: sym }), lines }
    }
    case 'earnings': {
      const lines: string[] = []
      if (ev.avg_abs_move_pct != null) {
        lines.push(fill(te.avgMove, { pct: num(ev.avg_abs_move_pct, locale, 1), n: ev.reports_measured ?? DASH }))
        if (ev.typical_move_home != null) lines.push(fill(te.typicalMove, { amount: fmtHome(ev.typical_move_home) }))
      }
      return { title: fill(te.earnings, { symbol: sym }), lines }
    }
    case 'check_changed': {
      const lines = (ev.changes ?? []).map((c) => fill(te.checkChange, { check: checkLabel(c.key, t), from: statusText(c.from, t), to: statusText(c.to, t) }))
      return { title: fill(te.checkChanged, { symbol: sym }), lines }
    }
    case 'analyst': {
      const lines: string[] = []
      if (ev.from_grade || ev.to_grade) lines.push(ev.from_grade && ev.to_grade && ev.from_grade !== ev.to_grade
        ? fill(te.gradeChange, { from: ev.from_grade, to: ev.to_grade }) : fill(te.grade, { grade: ev.to_grade ?? ev.from_grade }))
      if (ev.price_target != null) {
        lines.push(ev.prior_price_target != null
          ? fill(te.targetChange, { from: nativePrice(ev.prior_price_target, sym), to: nativePrice(ev.price_target, sym) })
          : fill(te.target, { to: nativePrice(ev.price_target, sym) }))
      }
      lines.push(te.targetsFollow)
      const action = ev.action ? (te.actions as Record<string, string>)[ev.action] ?? ev.action : te.actions.rating
      return { title: fill(te.analyst, { symbol: sym, firm: ev.firm ?? DASH, action }), lines }
    }
    case 'price_alert': {
      const price = nativePrice(ev.target_price, sym, ev.currency)
      const lines = ev.last_price != null ? [fill(te.priceAlertAt, { price: nativePrice(ev.last_price, sym, ev.currency) })] : []
      return { title: fill(ev.direction === 'below' ? te.priceAlertBelow : te.priceAlertAbove, { symbol: sym, price }), lines }
    }
    case 'economy': {
      const title = ev.code ? (te.economy as Record<string, string>)[ev.code] ?? ev.title : ev.title
      return { title, lines: ev.estimated ? [te.provisional] : [] }
    }
    default:
      return { title: ev.title, lines: ev.detail ? [ev.detail] : [] }
  }
}

/** One item of the Coming up feed. */
export const EventRow = memo(function EventRow({ ev, currency, showDate }: { ev: EventItem; currency: string; showDate?: string }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const te = t.comingUpPage
  const { fmt, hidden } = useMoney(currency)
  const { title, lines } = eventText(ev, t, locale, fmt, hidden)
  const Icon = ICONS[ev.type] ?? CalendarCheck
  const personal = ev.type === 'economy' || ev.type === 'price_alert'   // not "watchlist"-only news
  const muted = !ev.owned && !personal
  const iconColor = ev.type === 'dividend_payment' ? theme.colors.up
    : ev.type === 'check_changed' || ev.type === 'price_alert' ? theme.colors.warning : theme.colors.primary
  return (
    <li className="flex gap-3 py-3 min-w-0" style={{ borderTop: `1px solid ${theme.colors.border}` }}>
      <span className="shrink-0 w-9 h-9 rounded-full inline-flex items-center justify-center" aria-hidden="true"
        style={{ backgroundColor: theme.colors.surfaceAlt, color: iconColor }}>
        <Icon size={16} />
      </span>
      <div className="flex-1 min-w-0 flex flex-col gap-0.5">
        <p className="text-[14px] font-medium min-w-0 break-words" style={{ color: muted ? theme.colors.textSub : theme.colors.text }}>
          {ev.symbol ? (
            <Link href={`/stocks/${encodeURIComponent(ev.symbol)}`} className="underline-offset-2 hover:underline"
              aria-label={fill(t.stock.openPage, { symbol: ev.symbol })} style={{ color: 'inherit' }}>
              {title}
            </Link>
          ) : title}
        </p>
        {showDate && <p className="text-[12px] tabular-nums" style={{ color: theme.colors.textSub }}>{showDate}</p>}
        {lines.map((l, i) => (
          <p key={i} className="text-[12.5px] tabular-nums break-words" style={{ color: theme.colors.textSub }}>{l}</p>
        ))}
        {(ev.estimated || ev.recent || (!ev.owned && !personal)) && (
          <div className="flex flex-wrap gap-1.5 mt-0.5">
            {ev.recent && <Tag label={te.tags.recent} color={theme.colors.textSub} />}
            {ev.estimated && ev.type !== 'economy' && <Tag label={te.tags.estimated} color={theme.colors.warning} />}
            {!ev.owned && !personal && <Tag label={te.tags.watchlist} color={theme.colors.textSub} />}
            {ev.type === 'price_alert' && <Tag label={te.tags.alert} color={theme.colors.primary} />}
          </div>
        )}
      </div>
    </li>
  )
})

export const Tag = memo(function Tag({ label, color, title }: { label: string; color: string; title?: string }) {
  return (
    <span title={title} className="inline-block text-[10.5px] font-semibold px-1.5 py-px rounded-full whitespace-nowrap"
      style={{ color, border: `1px solid ${color}` }}>
      {label}
    </span>
  )
})
