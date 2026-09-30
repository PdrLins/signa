'use client'

import { Suspense, memo } from 'react'
import Link from 'next/link'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useDividendSummary, useMoney, useScope } from '@/hooks/usePortfolioInsights'
import { fill } from '@/lib/insights'
import { SectionCard, SoonBadge, TrackerHeader, useButtonStyles } from '@/components/profile/ui'
import { HideAmountsButton, PremiumHint, QueryError, ScopeSelect, SkeletonCards, Stat } from '@/components/tracker/ui'
import type { DividendTaxBlock } from '@/types/tracker'

export default function DividendTaxPage() {
  return (
    <Suspense fallback={null}>
      <TaxInner />
    </Suspense>
  )
}

const TypeRow = memo(function TypeRow({ row, currency }: { row: DividendTaxBlock['by_account_type'][number]; currency: string }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const tt = t.divTax
  const { fmt } = useMoney(currency)
  const name = (t.accountsPage.types as Record<string, string>)[row.account_type] ?? row.account_type
  return (
    <li className="py-3 flex flex-col gap-1 min-w-0" style={{ borderTop: `1px solid ${theme.colors.border}` }}>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[14px] font-semibold" style={{ color: theme.colors.text }}>{name}</span>
        <span className="text-[14px] font-semibold tabular-nums" style={{ color: theme.colors.text }}>{fmt(row.after_tax)}</span>
      </div>
      <p className="text-[12.5px] tabular-nums flex flex-wrap gap-x-3 gap-y-0.5" style={{ color: theme.colors.textSub }}>
        <span>{fill(tt.gross, { amount: fmt(row.gross) })}</span>
        {row.lost > 0 && <span style={{ color: theme.colors.warning }}>{fill(tt.lost, { amount: fmt(row.lost) })}</span>}
        {row.recoverable > 0 && <span>{fill(tt.recoverable, { amount: fmt(row.recoverable) })}</span>}
        {row.inside_fund > 0 && <span>{fill(tt.insideFund, { amount: fmt(row.inside_fund) })}</span>}
      </p>
    </li>
  )
})

function TaxInner() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const tt = t.divTax
  const btn = useButtonStyles()
  const { scope, query, setScope } = useScope()
  const q = useDividendSummary(scope, 'next12m')
  const d = q.data
  const tax = d?.tax ?? null
  const { fmt } = useMoney(d?.currency)

  return (
    <div className="space-y-4 pb-4 min-w-0 max-w-3xl">
      <TrackerHeader title={tt.title} subtitle={tt.subtitle} backHref={`/dividends${query}`} backLabel={t.divSummary.backToDividends}
        right={<div className="flex items-center gap-2"><SoonBadge label={t.tracker.premium} tone="primary" /><HideAmountsButton /></div>} />
      <ScopeSelect scope={scope} onChange={setScope} />

      {q.isLoading && <SkeletonCards heights={[120, 200]} />}
      {!!q.error && !d && <QueryError error={q.error} onRetry={() => q.refetch()} />}

      {d && !tax && (
        d.tax_reason === 'not_eligible' ? (
          <PremiumHint body={tt.reasons.not_eligible} />
        ) : (
          <section role="status" className="rounded-2xl p-4 flex flex-col items-start gap-3"
            style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.border}` }}>
            <p className="text-[13px]" style={{ color: theme.colors.textSub }}>
              {(tt.reasons as Record<string, string>)[d.tax_reason ?? ''] ?? tt.reasons.view_before}
            </p>
            <Link href="/profile" className={btn.secondary.className} style={btn.secondary.style}>{tt.openProfile}</Link>
          </section>
        )
      )}

      {d && tax && (
        <>
          <SectionCard title={tt.summaryTitle} subtitle={tt.summarySubtitle}>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              <Stat label={tt.stats.gross} value={fmt(tax.gross_total)} />
              <Stat label={tt.stats.lost} value={fmt(tax.lost)} color={tax.lost > 0 ? theme.colors.warning : undefined} sub={tt.stats.lostHelp} />
              <Stat label={tt.stats.recoverable} value={fmt(tax.recoverable)} sub={tt.stats.recoverableHelp} />
              <Stat label={tt.stats.afterTax} value={fmt(tax.after_tax_total)} />
            </div>
            <p className="text-[12.5px] tabular-nums" style={{ color: theme.colors.textSub }}>
              {fill(tt.cashReceived, { amount: fmt(tax.cash_received) })}
            </p>
          </SectionCard>

          <SectionCard title={tt.byTypeTitle}>
            {tax.by_account_type.length === 0 ? (
              <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{tt.noTypes}</p>
            ) : (
              <ul className="-mt-2">
                {tax.by_account_type.map((r) => <TypeRow key={r.account_type} row={r} currency={d.currency} />)}
              </ul>
            )}
          </SectionCard>

          {tax.inside_fund > 0 && (
            <SectionCard title={tt.insideTitle}>
              <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{fill(tt.insideBody, { amount: fmt(tax.inside_fund) })}</p>
            </SectionCard>
          )}

          {tax.untyped_accounts.length > 0 && (
            <SectionCard title={tt.untypedTitle}>
              <p className="text-[13px]" style={{ color: theme.colors.textSub }}>
                {fill(tt.untypedBody, { names: tax.untyped_accounts.map((a) => a.name).join(', ') })}
              </p>
              <Link href="/profile/accounts" className={`${btn.secondary.className} self-start`} style={btn.secondary.style}>{tt.setTypes}</Link>
            </SectionCard>
          )}

          <p className="text-[12px]" style={{ color: theme.colors.textHint }}>{tt.disclaimer}</p>
        </>
      )}
    </div>
  )
}
