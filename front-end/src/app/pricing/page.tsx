'use client'

import Link from 'next/link'
import { useMemo } from 'react'
import { ArrowLeft, Check } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { LangSwitcher } from '@/components/ui/LangSwitcher'

/** Public plans page (no sign-in needed), linked from the login page.
 *  Lists only what Signa actually ships in each plan; the limits mirror the
 *  back-end access catalog (10 stocks / 3 alerts free, premium unlimited). */
export default function PricingPage() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const tp = t.pricing
  const c = theme.colors

  const rows = useMemo(() => [
    { label: tp.rows.stocks, free: tp.values.ten, premium: tp.values.unlimited },
    { label: tp.rows.alerts, free: tp.values.three, premium: tp.values.unlimited },
    { label: tp.rows.prices, free: tp.values.min15, premium: tp.values.min1 },
    { label: tp.rows.extended, free: tp.values.no, premium: tp.values.yes },
    { label: tp.rows.crypto, free: tp.values.yes, premium: tp.values.yes },
    { label: tp.rows.intraday, free: tp.values.m5, premium: tp.values.m5 },
    { label: tp.rows.history, free: tp.values.y1, premium: tp.values.all },
    { label: tp.rows.tax, free: tp.values.no, premium: tp.values.yes },
    { label: tp.rows.allocation, free: tp.values.yes, premium: tp.values.yes },
    { label: tp.rows.plan, free: tp.values.no, premium: tp.values.yes },
    { label: tp.rows.incomeQuality, free: tp.values.no, premium: tp.values.yes },
    { label: tp.rows.similar, free: tp.values.no, premium: tp.values.yes },
    { label: tp.rows.events, free: tp.values.yes, premium: tp.values.yes },
    { label: tp.rows.checks, free: tp.values.yes, premium: tp.values.yes },
  ], [tp])

  const card = 'rounded-2xl p-6 flex flex-col gap-4 min-w-0'

  return (
    <div className="min-h-screen" style={{ backgroundColor: c.bg, color: c.text }}>
      <div className="max-w-5xl mx-auto px-4 py-6 md:py-10 flex flex-col gap-8">
        <header className="flex items-center justify-between gap-3">
          <Link href="/login"
            className="min-h-[44px] inline-flex items-center gap-2 text-sm font-medium rounded-lg px-2 focus-visible:outline focus-visible:outline-2"
            style={{ color: c.textSub, outlineColor: c.primary }}>
            <ArrowLeft size={16} aria-hidden="true" />{tp.back}
          </Link>
          <LangSwitcher />
        </header>

        <div className="flex flex-col gap-2">
          <h1 className="text-3xl md:text-4xl font-bold tracking-tight">{tp.title}</h1>
          <p className="text-base" style={{ color: c.textSub }}>{tp.subtitle}</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <section aria-labelledby="plan-free" className={card}
            style={{ backgroundColor: c.surface, border: `1px solid ${c.border}` }}>
            <div className="flex flex-col gap-1">
              <h2 id="plan-free" className="text-lg font-semibold">{tp.free.name}</h2>
              <p className="text-3xl font-bold tabular-nums">{tp.free.price}<span className="text-sm font-medium" style={{ color: c.textSub }}> {tp.perMonth}</span></p>
              <p className="text-sm" style={{ color: c.textSub }}>{tp.free.tagline}</p>
            </div>
            <ul className="flex flex-col gap-2.5">
              {tp.freeFeatures.map((f) => (
                <li key={f} className="flex gap-2.5 text-sm leading-snug">
                  <Check size={16} aria-hidden="true" className="shrink-0 mt-0.5" style={{ color: c.up }} />
                  <span>{f}</span>
                </li>
              ))}
            </ul>
            <Link href="/login"
              className="mt-auto min-h-[44px] inline-flex items-center justify-center rounded-xl text-sm font-semibold focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
              style={{ backgroundColor: c.primary, color: c.surface, outlineColor: c.primary }}>
              {tp.free.cta}
            </Link>
          </section>

          <section aria-labelledby="plan-premium" className={card}
            style={{ backgroundColor: c.surface, border: `1px solid ${c.primary}` }}>
            <div className="flex flex-col gap-1">
              <div className="flex items-center justify-between gap-2">
                <h2 id="plan-premium" className="text-lg font-semibold">{tp.premium.name}</h2>
                <span className="text-[11px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full"
                  style={{ color: c.primary, backgroundColor: c.primary + '1f' }}>{tp.premium.badge}</span>
              </div>
              <p className="text-3xl font-bold">{tp.premium.price}</p>
              <p className="text-sm" style={{ color: c.textSub }}>{tp.premium.tagline}</p>
            </div>
            <p className="text-sm font-medium" style={{ color: c.textSub }}>{tp.everythingInFree}</p>
            <ul className="flex flex-col gap-2.5">
              {tp.premiumFeatures.map((f) => (
                <li key={f} className="flex gap-2.5 text-sm leading-snug">
                  <Check size={16} aria-hidden="true" className="shrink-0 mt-0.5" style={{ color: c.primary }} />
                  <span>{f}</span>
                </li>
              ))}
            </ul>
            <button type="button" disabled aria-disabled="true"
              className="mt-auto min-h-[44px] rounded-xl text-sm font-semibold opacity-70 cursor-not-allowed"
              style={{ backgroundColor: c.surfaceAlt, color: c.text, border: `1px solid ${c.border}` }}>
              {tp.premium.cta}
            </button>
          </section>
        </div>

        <section aria-labelledby="plan-compare" className="flex flex-col gap-3">
          <h2 id="plan-compare" className="text-lg font-semibold">{tp.compareTitle}</h2>
          <div className="overflow-x-auto rounded-2xl" style={{ border: `1px solid ${c.border}` }}>
            <table className="w-full text-sm min-w-[480px]">
              <thead>
                <tr style={{ backgroundColor: c.surfaceAlt }}>
                  <th scope="col" className="text-left font-medium px-4 py-3" style={{ color: c.textSub }}><span className="sr-only">{tp.compareTitle}</span></th>
                  <th scope="col" className="text-left font-semibold px-4 py-3">{tp.free.name}</th>
                  <th scope="col" className="text-left font-semibold px-4 py-3" style={{ color: c.primary }}>{tp.premium.name}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.label} style={{ borderTop: `1px solid ${c.border}`, backgroundColor: c.surface }}>
                    <th scope="row" className="text-left font-normal px-4 py-3" style={{ color: c.textSub }}>{r.label}</th>
                    <td className="px-4 py-3 tabular-nums">{r.free}</td>
                    <td className="px-4 py-3 tabular-nums font-medium">{r.premium}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <ul className="flex flex-col gap-1 text-xs pb-6" style={{ color: c.textSub }}>
          {tp.notes.map((n) => <li key={n}>{n}</li>)}
        </ul>
      </div>
    </div>
  )
}
