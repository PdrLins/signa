'use client'

import { Suspense, memo, useMemo } from 'react'
import { useParams } from 'next/navigation'
import { AlertTriangle } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useIncomeQuality, useScope } from '@/hooks/usePortfolioInsights'
import { fill, shortDate, signedPct } from '@/lib/insights'
import { pct, spct } from '@/components/holdings/format'
import { SectionCard, TrackerHeader } from '@/components/profile/ui'
import { QueryError, SkeletonCards, Stat, useSignColor } from '@/components/tracker/ui'
import type { IncomeQuality } from '@/types/tracker'

export default function IncomeQualityPage() {
  return (
    <Suspense fallback={null}>
      <Inner />
    </Suspense>
  )
}

const ReturnBar = memo(function ReturnBar({ label, value, max, color }: { label: string; value: number | null; max: number; color: string }) {
  const theme = useTheme()
  const w = value !== null && max > 0 ? Math.max(2, (Math.abs(value) / max) * 100) : 0
  return (
    <li className="flex flex-col gap-1 min-w-0">
      <div className="flex items-baseline justify-between gap-2 text-[13px]">
        <span className="font-semibold truncate" style={{ color: theme.colors.text }}>{label}</span>
        <span className="tabular-nums shrink-0" style={{ color: theme.colors.text }}>{signedPct(value, 1)}</span>
      </div>
      <div className="h-3 rounded-full overflow-hidden" aria-hidden="true" style={{ backgroundColor: theme.colors.surfaceAlt }}>
        <div className="h-full rounded-full" style={{ width: `${w}%`, backgroundColor: color }} />
      </div>
    </li>
  )
})

function Payouts({ q }: { q: IncomeQuality }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const tq = t.incomeQuality
  const pays = q.payout_history.payments
  const max = useMemo(() => Math.max(0, ...pays.map((p) => p.amount)), [pays])
  if (pays.length === 0) return <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{tq.noPayouts}</p>
  return (
    <div className="flex flex-col gap-2">
      <ol aria-label={tq.payoutsAria} className="flex items-end gap-1 h-28 min-w-0">
        {pays.map((p) => {
          const label = fill(tq.payoutBar, { date: shortDate(p.ex_date, locale, true), amount: p.amount.toFixed(4), change: spct(p.change_pct, 1) })
          return (
            <li key={p.ex_date} aria-label={label} title={label} className="flex-1 min-w-0 h-full flex items-end">
              <div className="w-full rounded-t-[3px]" style={{
                height: `${max > 0 ? (p.amount / max) * 100 : 0}%`, minHeight: 2,
                backgroundColor: p.special ? theme.colors.accent : theme.colors.primary,
              }} />
            </li>
          )
        })}
      </ol>
      <p className="text-[12.5px] tabular-nums" style={{ color: theme.colors.textSub }}>
        {q.payout_history.min_change_pct !== null && q.payout_history.max_change_pct !== null
          ? fill(tq.variability, { min: spct(q.payout_history.min_change_pct, 0), max: spct(q.payout_history.max_change_pct, 0) })
          : tq.variabilityUnknown}
      </p>
    </div>
  )
}

function Inner() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const tq = t.incomeQuality
  const params = useParams<{ symbol: string }>()
  const symbol = decodeURIComponent(params.symbol ?? '').toUpperCase()
  const { query } = useScope()
  const query_ = useIncomeQuality(symbol)
  const q = query_.data
  const signColor = useSignColor()
  const tr = q?.total_return_5y ?? null
  const max = Math.max(Math.abs(tr?.symbol_pct ?? 0), Math.abs(tr?.underlying_pct ?? 0))

  return (
    <div className="space-y-4 pb-4 min-w-0 max-w-3xl">
      <TrackerHeader title={fill(tq.title, { symbol })} subtitle={q?.name ?? undefined}
        backHref={`/dividends${query}`} backLabel={t.divSummary.backToDividends} />

      {query_.isLoading && <SkeletonCards heights={[140, 160, 160]} />}
      {!!query_.error && !q && <QueryError error={query_.error} onRetry={() => query_.refetch()} />}

      {q && (
        <>
          <SectionCard title={tq.sourceTitle}>
            <div className="grid grid-cols-2 gap-2">
              <Stat label={tq.yield} value={pct(q.yield_pct, 2)} />
              <Stat label={tq.kind} value={(tq.classes as Record<string, string>)[q.income_class] ?? q.income_class} />
            </div>
            <p className="text-[14px]" style={{ color: theme.colors.text }}>
              {(tq.sources as Record<string, string>)[q.yield_source] ?? q.yield_source}
            </p>
            {(q.flags ?? []).includes('return_of_capital_possible') && (
              <p className="flex items-start gap-2 text-[13px] rounded-xl px-3 py-2.5" style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.text }}>
                <AlertTriangle size={16} aria-hidden="true" className="shrink-0 mt-0.5" style={{ color: theme.colors.warning }} />
                {tq.roc}
              </p>
            )}
          </SectionCard>

          <SectionCard title={tq.returnTitle}
            subtitle={tr ? fill(tq.returnPeriod, { start: shortDate(tr.start, locale, true), end: shortDate(tr.end, locale, true) }) : undefined}>
            {!tr ? (
              <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{tq.noReturn}</p>
            ) : (
              <>
                <ul className="flex flex-col gap-3">
                  <ReturnBar label={q.symbol} value={tr.symbol_pct} max={max} color={theme.colors.primary} />
                  {q.underlying && <ReturnBar label={fill(tq.underlying, { symbol: q.underlying })} value={tr.underlying_pct} max={max} color={theme.colors.textSub} />}
                </ul>
                {q.comparison?.difference_pct != null && (
                  <p className="text-[13px] tabular-nums" style={{ color: signColor(q.comparison.difference_pct) }}>
                    {fill(q.comparison.difference_pct >= 0 ? tq.ahead : tq.behind, { pts: pct(Math.abs(q.comparison.difference_pct), 1), symbol: q.underlying ?? '' })}
                  </p>
                )}
                {q.comparison?.currency_mismatch && <p className="text-[12px]" style={{ color: theme.colors.textHint }}>{tq.currencyMismatch}</p>}
                <p className="text-[12px]" style={{ color: theme.colors.textHint }}>{tq.returnNote}</p>
              </>
            )}
          </SectionCard>

          <SectionCard title={tq.payoutsTitle} subtitle={tq.payoutsHelp}>
            <Payouts q={q} />
          </SectionCard>
          <p className="text-[12px]" style={{ color: theme.colors.textHint }}>{t.tracker.notAdvice}</p>
        </>
      )}
    </div>
  )
}
