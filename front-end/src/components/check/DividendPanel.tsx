'use client'

import { memo, useMemo } from 'react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore, intlLocale } from '@/store/i18nStore'
import { Panel, mono } from '@/components/insights/Panel'
import { DASH, fill, shortDate } from '@/lib/insights'
import type en from '@/lib/i18n/en.json'
import type { DividendProfile, DividendRule, DividendScheduleRow } from '@/types/check'

type T = typeof en

/** Per-share amount in the listing currency, locale-formatted ("C$0.97"). */
function amountText(v: number | null | undefined, currency: string | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return DASH
  const sym = currency === 'CAD' ? 'C$' : currency && currency !== 'USD' ? `${currency} ` : '$'
  return `${sym}${v.toLocaleString(intlLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`
}

/** FRACTION -> locale percent ("3.12 %" / "3,12%"). */
function fracPct(v: number | null | undefined, digits = 2, signed = false): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return DASH
  return (v).toLocaleString(intlLocale(), {
    style: 'percent', minimumFractionDigits: digits, maximumFractionDigits: digits,
    ...(signed ? { signDisplay: 'exceptZero' as const } : {}),
  })
}

function numText(v: unknown, digits = 1): string | null {
  if (typeof v !== 'number' || !Number.isFinite(v)) return null
  return v.toLocaleString(intlLocale(), { maximumFractionDigits: digits })
}

/** A dividend rule through t.check.dividend.rules[code]; English fallback. */
export function dividendRuleText(rule: DividendRule, t: T, locale: string, currency: string | null | undefined): string {
  const tpl = (t.check.dividend.rules as Record<string, string>)[rule.code]
  if (!tpl) return rule.text
  const vars: Record<string, string | number | null> = {}
  for (const [k, v] of Object.entries(rule.params ?? {})) {
    if (v === null || v === undefined || typeof v === 'boolean') vars[k] = null
    else if (k === 'date' || k === 'pay_date') vars[k] = shortDate(String(v), locale, true)
    else if (k === 'amount') vars[k] = amountText(Number(v), currency)
    else if (typeof v === 'number') vars[k] = numText(v, k === 'pct' || k === 'yield' || k === 'avg' ? 2 : 1)
    else vars[k] = v
  }
  return fill(tpl, vars)
}

const Tag = memo(function Tag({ label, color }: { label: string; color: string }) {
  return (
    <span
      className="inline-block text-[10.5px] font-semibold px-1.5 py-px rounded-full align-middle whitespace-nowrap"
      style={{ color, border: `1px solid ${color}` }}
    >
      {label}
    </span>
  )
})

const RuleItem = memo(function RuleItem({ rule, text, effectLabel, color }: {
  rule: DividendRule
  text: string
  effectLabel: string
  color: string
}) {
  const theme = useTheme()
  return (
    <li
      className="rounded-[10px] p-3 flex flex-col gap-1 min-w-0"
      style={{ backgroundColor: theme.colors.surfaceAlt, borderLeft: `3px solid ${color}` }}
      data-rule={rule.code}
    >
      <span className="text-[11px] font-semibold" style={{ color }}>{effectLabel}</span>
      <p className="text-[13px] leading-snug break-words" style={{ color: theme.colors.text }}>{text}</p>
    </li>
  )
})

const AgendaRow = memo(function AgendaRow({ row, currency, locale, estLabel, hintColor }: {
  row: DividendScheduleRow
  currency: string | null
  locale: string
  estLabel: string
  hintColor: string
}) {
  const theme = useTheme()
  return (
    <tr style={{ borderBottom: `1px solid ${theme.colors.border}` }}>
      <td className="py-1.5 pr-2 align-top" style={{ color: theme.colors.text }}>
        <span className="tabular-nums">{shortDate(row.ex_date, locale, true)}</span>
        {row.estimated && <> <Tag label={estLabel} color={hintColor} /></>}
      </td>
      <td className="py-1.5 pr-2 align-top tabular-nums" style={{ color: theme.colors.textSub }}>
        {row.pay_date ? shortDate(row.pay_date, locale, true) : DASH}
      </td>
      <td className="py-1.5 text-right align-top tabular-nums" style={{ ...mono, color: theme.colors.text }}>
        {row.amount != null ? `≈ ${amountText(row.amount, currency)}` : DASH}
      </td>
    </tr>
  )
})

const PaidRow = memo(function PaidRow({ exDate, amount, special, currency, locale, specialLabel, hintColor }: {
  exDate: string
  amount: number
  special: boolean
  currency: string | null
  locale: string
  specialLabel: string
  hintColor: string
}) {
  const theme = useTheme()
  return (
    <tr style={{ borderBottom: `1px solid ${theme.colors.border}` }}>
      <td className="py-1.5 pr-2 tabular-nums" style={{ color: theme.colors.text }}>
        {shortDate(exDate, locale, true)}
        {special && <> <Tag label={specialLabel} color={hintColor} /></>}
      </td>
      <td className="py-1.5 text-right tabular-nums" style={{ ...mono, color: theme.colors.text }}>{amountText(amount, currency)}</td>
    </tr>
  )
})

/** Dividend facts, payment agenda (next 12 months), last payments and the
 *  brain's deterministic dividend rules. Used by both Check result views. */
export function DividendPanel({ profile, rules, symbol, currency, rrWithDividend }: {
  profile: DividendProfile | null | undefined
  rules?: DividendRule[] | null
  symbol: string
  currency: string | null
  rrWithDividend?: number | null
}) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const td = t.check.dividend
  const ccy = profile?.currency ?? currency
  const hint = theme.colors.textSub

  const effectColor = useMemo(() => ({
    positive: theme.colors.up, negative: theme.colors.down, caution: theme.colors.warning, info: theme.colors.textSub,
  }), [theme])

  const ruleRows = useMemo(
    () => (rules ?? []).map((r) => ({ rule: r, text: dividendRuleText(r, t, locale, ccy) })),
    [rules, t, locale, ccy],
  )

  const stats = useMemo(() => {
    if (!profile || !profile.pays_dividend) return []
    const freq = profile.frequency ? (td.frequencies as Record<string, string>)[profile.frequency] ?? profile.frequency : DASH
    return [
      { k: td.pays, v: td.yes },
      { k: td.yield, v: fracPct(profile.yield, 2) },
      { k: td.annual, v: profile.annual_rate != null ? fill(td.annualValue, { amount: amountText(profile.annual_rate, ccy) }) : DASH },
      { k: td.frequency, v: freq },
      { k: td.payout, v: fracPct(profile.payout_ratio, 0) },
      { k: td.fiveYearYield, v: fracPct(profile.five_year_avg_yield, 2) },
      { k: td.nextEx, v: profile.next_ex_date ? shortDate(profile.next_ex_date, locale, true) : DASH, est: !!profile.next_ex_date && !!profile.next_estimated },
      { k: td.nextPay, v: profile.next_pay_date ? shortDate(profile.next_pay_date, locale, true) : DASH, est: !!profile.next_pay_date && !!profile.next_pay_estimated },
      // stock page: growth over 1/3/5/10 years (PERCENT per year); else the 5-year CAGR (FRACTION)
      ...(['growth_1y_pct', 'growth_3y_pct', 'growth_5y_pct', 'growth_10y_pct'] as const).some((g) => profile[g] != null)
        ? (['growth_1y_pct', 'growth_3y_pct', 'growth_5y_pct', 'growth_10y_pct'] as const).map((g) => ({
          k: fill(td.growthN, { n: g.replace('growth_', '').replace('y_pct', '') }),
          v: profile[g] != null ? fill(td.growthValue, { pct: fracPct((profile[g] as number) / 100, 1, true) }) : DASH,
        }))
        : [{ k: td.growth, v: profile.growth_5y_cagr != null ? fill(td.growthValue, { pct: fracPct(profile.growth_5y_cagr, 1, true) }) : DASH }],
      { k: td.yearsNoCut, v: profile.years_without_cut != null ? fill(td.yearsValue, { n: numText(profile.years_without_cut, 0) }) : DASH },
    ] as { k: string; v: string; est?: boolean }[]
  }, [profile, td, ccy, locale])

  const badges = useMemo(() => {
    if (!profile) return []
    const out: { label: string; color: string }[] = []
    if (profile.suspended) out.push({ label: td.badgeSuspended, color: theme.colors.down })
    if (profile.recent_cut && profile.last_cut_date && !profile.suspended) {
      out.push({ label: fill(td.badgeCut, { date: shortDate(profile.last_cut_date, locale, true) }), color: theme.colors.down })
    }
    if (profile.growth_5y_cagr != null && profile.growth_5y_cagr > 0) out.push({ label: td.badgeGrowing, color: theme.colors.up })
    if (!profile.recent_cut && profile.years_without_cut != null && profile.years_without_cut >= 5) {
      out.push({ label: fill(td.badgeNoCut, { n: Math.floor(profile.years_without_cut) }), color: theme.colors.up })
    }
    return out
  }, [profile, td, theme, locale])

  const emptyText = !profile ? td.unavailable
    : profile.reason === 'crypto' ? td.crypto
      : profile.suspended ? fill(td.suspended, { symbol })
        : profile.reason === 'unavailable' ? td.unavailable
          : fill(td.none, { symbol })

  const rulesBlock = ruleRows.length > 0 && (
    <div className="flex flex-col gap-2">
      <h3 className="text-[13px] font-semibold" style={{ color: theme.colors.text }}>{td.rulesTitle}</h3>
      <ul className="flex flex-col gap-2">
        {ruleRows.map(({ rule, text }, i) => (
          <RuleItem
            key={`${rule.code}-${i}`}
            rule={rule}
            text={text}
            effectLabel={(td.effects as Record<string, string>)[rule.effect] ?? rule.effect}
            color={effectColor[rule.effect] ?? theme.colors.textSub}
          />
        ))}
      </ul>
      {rrWithDividend != null && (
        <p className="text-[12.5px]" style={{ color: theme.colors.textSub }}>
          {fill(td.rrWithDividend, { rr: numText(rrWithDividend, 2) })}
        </p>
      )}
    </div>
  )

  const badgeRow = badges.length > 0 && (
    <ul className="flex flex-wrap gap-1.5" aria-label={td.title}>
      {badges.map((b) => (
        <li key={b.label}><Tag label={b.label} color={b.color} /></li>
      ))}
    </ul>
  )

  if (!profile || !profile.pays_dividend) {
    return (
      <Panel title={td.title}>
        <div className="flex flex-col gap-3">
          <p className="text-[13px]" style={{ color: theme.colors.textSub }}>
            <span className="font-semibold" style={{ color: theme.colors.text }}>{td.pays}: {td.no}.</span>{' '}{emptyText}
          </p>
          {badgeRow}
          {rulesBlock}
        </div>
      </Panel>
    )
  }

  return (
    <Panel title={td.title} subtitle={td.subtitle}>
      <div className="flex flex-col gap-4 min-w-0">
        {badgeRow}

        <dl className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2.5">
          {stats.map((x) => (
            <div key={x.k} className="rounded-[10px] px-3 py-2.5 flex flex-col gap-1 min-w-0" style={{ backgroundColor: theme.colors.surfaceAlt }}>
              <dt className="text-[11px]" style={{ color: theme.colors.textSub }}>{x.k}</dt>
              <dd className="text-[14px] tabular-nums break-words" style={{ ...mono, color: theme.colors.text }}>
                {x.v}
                {x.est && <> <Tag label={td.estimated} color={hint} /></>}
              </dd>
            </div>
          ))}
        </dl>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 min-w-0">
          <div className="flex flex-col gap-1.5 min-w-0">
            <h3 className="text-[13px] font-semibold" style={{ color: theme.colors.text }}>{td.upcomingTitle}</h3>
            {profile.upcoming.length === 0 ? (
              <p className="text-[12.5px]" style={{ color: theme.colors.textSub }}>{td.upcomingNone}</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-[12.5px]">
                  <caption className="sr-only">{fill(td.upcomingCaption, { symbol })}</caption>
                  <thead>
                    <tr style={{ color: theme.colors.textHint, borderBottom: `1px solid ${theme.colors.border}` }}>
                      <th scope="col" className="py-1 pr-2 text-left font-medium">{td.exDate}</th>
                      <th scope="col" className="py-1 pr-2 text-left font-medium">{td.payDate}</th>
                      <th scope="col" className="py-1 text-right font-medium">{td.amount}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {profile.upcoming.map((row) => (
                      <AgendaRow key={row.ex_date} row={row} currency={ccy} locale={locale} estLabel={td.estimated} hintColor={hint} />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="flex flex-col gap-1.5 min-w-0">
            <h3 className="text-[13px] font-semibold" style={{ color: theme.colors.text }}>{td.lastTitle}</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-[12.5px]">
                <caption className="sr-only">{fill(td.lastCaption, { symbol })}</caption>
                <thead>
                  <tr style={{ color: theme.colors.textHint, borderBottom: `1px solid ${theme.colors.border}` }}>
                    <th scope="col" className="py-1 pr-2 text-left font-medium">{td.exDate}</th>
                    <th scope="col" className="py-1 text-right font-medium">{td.amount}</th>
                  </tr>
                </thead>
                <tbody>
                  {profile.last_payments.map((p) => (
                    <PaidRow
                      key={p.ex_date}
                      exDate={p.ex_date}
                      amount={p.amount}
                      special={p.special}
                      currency={ccy}
                      locale={locale}
                      specialLabel={td.special}
                      hintColor={hint}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {rulesBlock}

        <p className="text-[11.5px] leading-snug" style={{ color: theme.colors.textHint }}>
          {td.exDateHelp} {td.estimatedHelp}
        </p>
      </div>
    </Panel>
  )
}
