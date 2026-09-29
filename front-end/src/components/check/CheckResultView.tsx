'use client'

import { forwardRef } from 'react'
import Link from 'next/link'
import { CheckCircle2, Clock, XCircle, RefreshCw } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { Panel, mono } from '@/components/insights/Panel'
import { DecisionTrail } from '@/components/signals/DecisionTrail'
import { fill, formatReason, money, nativePrice, num, shortDate, etTime, DASH } from '@/lib/insights'
import { formatCheckText } from '@/lib/check'
import type { CheckResult, CheckVerdict } from '@/types/check'

export function useVerdictStyle() {
  const theme = useTheme()
  return (v: CheckVerdict) =>
    v === 'BUY_NOW' ? { color: theme.colors.up, Icon: CheckCircle2 }
      : v === 'WAIT' ? { color: theme.colors.warning, Icon: Clock }
        : { color: theme.colors.down, Icon: XCircle }
}

/** Verdict card + key numbers + the reused decision trail + caveats. */
export const CheckResultView = forwardRef<HTMLHeadingElement, {
  result: CheckResult
  onRecheck: () => void
  recheckDisabled?: boolean
}>(function CheckResultView({ result: r, onRecheck, recheckDisabled }, headingRef) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const tc = t.check
  const style = useVerdictStyle()(r.verdict)
  const ctx = { symbol: r.symbol, currency: r.currency, locale }
  const primary = r.reasons[0] ?? null
  const headlineTpl = (tc.headline as Record<string, string>)[r.headline.code]
  const headline = headlineTpl
    ? fill(headlineTpl, { symbol: r.symbol, reason: primary ? formatReason(primary, t).replace(/\.$/, '') : null })
    : r.headline.text
  const assetLabel = (tc.assetClass as Record<string, string>)[r.asset_class] ?? r.asset_class
  const corr = r.trail.correlation
  const corrText = corr?.max_corr != null && corr.max_corr_symbol
    ? fill(tc.correlationValue, { corr: corr.max_corr.toFixed(2), symbol: corr.max_corr_symbol })
    : tc.correlationNone
  const lv = r.levels
  const sz = r.size
  const earn = r.earnings
  const earnText = !earn ? tc.earningsNa
    : earn.date ? `${shortDate(earn.date, locale, true)}${earn.blackout ? ` · ${tc.earningsBlackout}` : ''}`
      : tc.earningsNone

  const tiles: { k: string; v: string; sub?: string }[] = [
    { k: tc.price, v: nativePrice(r.price, r.symbol, r.currency) },
    { k: tc.entry, v: nativePrice(lv.entry, r.symbol, r.currency) },
    { k: tc.stop, v: nativePrice(lv.stop, r.symbol, r.currency) },
    { k: tc.target, v: nativePrice(lv.target, r.symbol, r.currency) },
    { k: tc.rr, v: lv.rr != null ? fill(tc.rrValue, { rr: num(lv.rr, 1), min: num(lv.min_rr, 1) }) : DASH },
    {
      k: fill(tc.size, { pct: sz?.risk_per_trade_pct ?? 1 }),
      v: sz ? fill(tc.sizeValue, { shares: sz.shares >= 10 ? sz.shares.toFixed(0) : sz.shares.toFixed(3), alloc: money(sz.alloc_usd, 0) }) : tc.sizeNone,
      sub: sz && sz.risk_usd != null ? fill(tc.sizeRisk, { risk: money(sz.risk_usd, 0), pct: sz.risk_pct != null ? sz.risk_pct.toFixed(1) : null }) : undefined,
    },
    { k: tc.earnings, v: earnText },
    { k: tc.correlation, v: corrText },
  ]

  const stamp = [
    r.cached ? tc.cached : null,
    fill(tc.checkedAt, { time: etTime(r.checked_at, locale) }),
  ].filter(Boolean).join(' · ')

  return (
    <div className="flex flex-col gap-4 md:gap-6">
      <section
        aria-labelledby="check-verdict"
        className="rounded-2xl p-5 md:p-6 flex flex-col gap-4"
        style={{
          backgroundColor: theme.colors.surface,
          border: `1px solid ${theme.colors.border}`,
          borderLeft: `4px solid ${style.color}`,
        }}
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-start gap-3 min-w-0">
            <style.Icon size={32} aria-hidden="true" className="shrink-0 mt-0.5" style={{ color: style.color }} />
            <div className="flex flex-col gap-1 min-w-0">
              <h2
                id="check-verdict"
                ref={headingRef}
                tabIndex={-1}
                className="text-[24px] md:text-[28px] font-semibold tracking-tight outline-none"
                style={{ color: style.color }}
              >
                {(tc.verdict as Record<string, string>)[r.verdict]}
              </h2>
              <p className="text-[13px]" style={{ color: theme.colors.textSub }}>
                <span style={{ ...mono, color: theme.colors.text }}>{r.symbol}</span>
                {r.name && <> · {r.name}</>}
                {' · '}{assetLabel}
                {r.exchange && <> · {r.exchange}</>}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 text-[12px]" style={{ color: theme.colors.textSub }}>
            <span>{stamp}</span>
            <button
              type="button"
              onClick={onRecheck}
              disabled={recheckDisabled}
              aria-label={fill(tc.recheckLabel, { symbol: r.symbol })}
              className="inline-flex items-center gap-1.5 h-8 px-2.5 rounded-lg text-[12px] font-medium disabled:opacity-50 focus-visible:outline focus-visible:outline-2"
              style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.primary, outlineColor: theme.colors.primary }}
            >
              <RefreshCw size={13} aria-hidden="true" />
              {tc.recheck}
            </button>
          </div>
        </div>

        <p className="text-[15px] leading-relaxed" style={{ color: theme.colors.text }}>{headline}</p>

        {r.reasons.length > 1 && (
          <div className="flex flex-col gap-1.5">
            <h3 className="text-[13px] font-semibold" style={{ color: theme.colors.text }}>{tc.why}</h3>
            <ul className="flex flex-col gap-1 list-disc pl-5">
              {r.reasons.map((x, i) => (
                <li key={i} className="text-[13px]" style={{ color: theme.colors.text }}>{formatReason(x, t)}</li>
              ))}
            </ul>
          </div>
        )}

        {r.what_would_change.length > 0 && (
          <div className="flex flex-col gap-1.5">
            <h3 className="text-[13px] font-semibold" style={{ color: theme.colors.text }}>{tc.whatWouldChange}</h3>
            <ul className="flex flex-col gap-1 list-disc pl-5">
              {r.what_would_change.map((h) => (
                <li key={h.code} className="text-[13px]" style={{ color: theme.colors.text }}>{formatCheckText(h, 'hints', t, ctx)}</li>
              ))}
            </ul>
          </div>
        )}

        {r.notes.length > 0 && (
          <ul className="flex flex-col gap-1">
            {r.notes.map((n) => (
              <li key={n.code} className="text-[12px]" style={{ color: theme.colors.textSub }}>{formatCheckText(n, 'notes', t, ctx)}</li>
            ))}
          </ul>
        )}

        <dl className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
          {tiles.map((x) => (
            <div key={x.k} className="rounded-[10px] px-3 py-2.5 flex flex-col gap-1 min-w-0" style={{ backgroundColor: theme.colors.surfaceAlt }}>
              <dt className="text-[11px]" style={{ color: theme.colors.textSub }}>{x.k}</dt>
              <dd className="text-[14px] tabular-nums break-words" style={{ ...mono, color: theme.colors.text }}>{x.v}</dd>
              {x.sub && <dd className="text-[11px]" style={{ color: theme.colors.textSub }}>{x.sub}</dd>}
            </div>
          ))}
        </dl>
      </section>

      <DecisionTrail
        trail={r.trail}
        options={{
          title: tc.trailTitle,
          orderTitle: tc.orderTitle,
          orderStatus: { label: r.verdict === 'BUY_NOW' ? tc.orderBuy : tc.orderNo, active: r.verdict === 'BUY_NOW' },
          showOutcomes: false,
        }}
      />

      <Panel title={tc.caveatsTitle}>
        <ul className="flex flex-col gap-1.5">
          {r.caveats.map((c) => (
            <li key={c.code} className="text-[13px]" style={{ color: theme.colors.textSub }}>
              {formatCheckText(c, 'caveats', t, ctx)}
            </li>
          ))}
        </ul>
        <Link
          href="/performance"
          className="mt-3 inline-block text-[13px] font-medium hover:underline focus-visible:outline focus-visible:outline-2 rounded"
          style={{ color: theme.colors.accent, outlineColor: theme.colors.primary }}
        >
          {tc.isItWorking} →
        </Link>
      </Panel>
    </div>
  )
})
