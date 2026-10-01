'use client'

import { memo, useEffect, useId, useMemo, useState } from 'react'
import Link from 'next/link'
import { AlertTriangle } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useToast } from '@/hooks/useToast'
import { useAllocation, useAllocationPlan, useMoney, useSaveTargets } from '@/hooks/usePortfolioInsights'
import { toHoldingsError } from '@/hooks/useHoldings'
import { SymbolListText } from '@/components/tracker/SymbolLink'
import { fill } from '@/lib/insights'
import { trackerErrorText } from '@/lib/trackerErrors'
import { pct } from '@/components/holdings/format'
import { SectionCard, Segmented, useButtonStyles, useFieldStyle } from '@/components/profile/ui'
import { Treemap } from '@/components/tracker/Treemap'
import { className as classLabel, warningText } from '@/components/tracker/text'
import { ChipGroup, EmptyHoldings, Freshness, QueryError, SkeletonCards } from '@/components/tracker/ui'
import type { AllocClass, Allocation, AllocationPlan, Scope } from '@/types/tracker'

const CLASSES: AllocClass[] = ['stocks', 'broad_etfs', 'option_income_etfs', 'cash_like', 'crypto', 'other']
const AMOUNTS = ['500', '1000', '5000'] as const

function useClassColors(): Record<AllocClass, string> {
  const theme = useTheme()
  return useMemo(() => ({
    stocks: theme.colors.primary,
    broad_etfs: theme.colors.up,
    option_income_etfs: theme.colors.warning,
    cash_like: theme.colors.textSub,
    crypto: theme.colors.accent,
    other: theme.colors.down,
  }), [theme])
}

const MixBar = memo(function MixBar({ a }: { a: Allocation }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const ta = t.insightsPage.allocation
  const colors = useClassColors()
  const { fmt } = useMoney(a.home_currency)
  const mix = useMemo(() => a.mix.filter((m) => m.pct > 0), [a.mix])
  const summary = mix.map((m) => `${classLabel(m.class, t)} ${pct(m.pct, 0)}`).join(', ')
  return (
    <div className="flex flex-col gap-3">
      <div className="flex h-4 rounded-full overflow-hidden" role="img" aria-label={fill(ta.mixAria, { mix: summary })}
        style={{ backgroundColor: theme.colors.surfaceAlt }}>
        {mix.map((m) => <div key={m.class} style={{ width: `${m.pct}%`, backgroundColor: colors[m.class] }} />)}
      </div>
      <ul className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1.5">
        {mix.map((m) => (
          <li key={m.class} className="flex items-center justify-between gap-2 text-[13px] min-w-0">
            <span className="inline-flex items-center gap-2 min-w-0" style={{ color: theme.colors.text }}>
              <span aria-hidden="true" className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ backgroundColor: colors[m.class] }} />
              <span className="truncate">{classLabel(m.class, t)}</span>
            </span>
            <span className="tabular-nums shrink-0" style={{ color: theme.colors.textSub }}>
              <span className="font-semibold" style={{ color: theme.colors.text }}>{pct(m.pct, 1)}</span> · {fmt(m.value_home, 0)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
})

function TargetsEditor({ a }: { a: Allocation }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const ta = t.insightsPage.allocation
  const toast = useToast()
  const field = useFieldStyle()
  const btn = useButtonStyles()
  const save = useSaveTargets()
  const baseId = useId()
  const current = useMemo(() => new Map(a.mix.map((m) => [m.class, m.pct])), [a.mix])
  const [vals, setVals] = useState<Record<string, string>>({})
  // No targets yet: a short explanation and one button, not six empty fields.
  const [editing, setEditing] = useState(!!a.targets)
  // Reset the form whenever the saved targets change.
  useEffect(() => {
    const next: Record<string, string> = {}
    for (const c of CLASSES) next[c] = a.targets && a.targets[c] ? String(a.targets[c]) : ''
    setVals(next)
    setEditing(!!a.targets)
  }, [a.targets])
  // "Set targets" starts from today's mix (whole numbers that add up to 100).
  const startFromMix = () => {
    const raw = CLASSES.map((c) => Math.round(current.get(c) ?? 0))
    const diff = 100 - raw.reduce((s, n) => s + n, 0)
    const big = raw.indexOf(Math.max(...raw))
    if (big >= 0) raw[big] += diff
    const next: Record<string, string> = {}
    CLASSES.forEach((c, i) => { next[c] = raw[i] > 0 ? String(raw[i]) : '' })
    setVals(next)
    setEditing(true)
  }
  const nums = CLASSES.map((c) => (vals[c]?.trim() ? Number(vals[c].replace(',', '.')) : 0))
  const invalid = nums.some((n) => !Number.isFinite(n) || n < 0 || n > 100)
  const sum = invalid ? NaN : nums.reduce((s, n) => s + n, 0)
  const ok = !invalid && Math.abs(sum - 100) < 0.011
  const onSave = () => {
    const targets: Partial<Record<AllocClass, number>> = {}
    CLASSES.forEach((c, i) => { targets[c] = nums[i] })
    save.mutate(targets, {
      onSuccess: () => toast.show(ta.targetsSaved, 'success', 2000),
      onError: (e) => toast.show(trackerErrorText(e, t), 'error'),
    })
  }
  const onClear = () => save.mutate(null, {
    onSuccess: () => toast.show(ta.targetsCleared, 'success', 2000),
    onError: (e) => toast.show(trackerErrorText(e, t), 'error'),
  })
  if (!editing) {
    return (
      <SectionCard title={ta.targetsTitle} subtitle={ta.targetsHelp}>
        <button type="button" onClick={startFromMix} className={`${btn.primary.className} self-start`} style={btn.primary.style}>
          {ta.setTargets}
        </button>
      </SectionCard>
    )
  }
  return (
    <SectionCard title={ta.targetsTitle} subtitle={ta.targetsHelp}>
      <form className="flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); if (ok) onSave() }}>
        <ul className="flex flex-col gap-2">
          {CLASSES.map((c) => (
            <li key={c} className="flex items-center gap-3 min-w-0">
              <label htmlFor={`${baseId}-${c}`} className="flex-1 min-w-0 text-[13px]" style={{ color: theme.colors.text }}>
                {classLabel(c, t)}
                <span className="block text-[11.5px] tabular-nums" style={{ color: theme.colors.textHint }}>
                  {fill(ta.nowPct, { pct: pct(current.get(c) ?? 0, 1) })}
                </span>
              </label>
              <div className="flex items-center gap-1.5 shrink-0">
                <input id={`${baseId}-${c}`} inputMode="decimal" value={vals[c] ?? ''} placeholder="0"
                  onChange={(e) => setVals((v) => ({ ...v, [c]: e.target.value }))}
                  className={`${field.input} !w-20 text-right tabular-nums`} style={field.style} />
                <span aria-hidden="true" className="text-[13px]" style={{ color: theme.colors.textSub }}>%</span>
              </div>
            </li>
          ))}
        </ul>
        <p role="status" aria-live="polite" className="text-[13px] tabular-nums font-medium"
          style={{ color: ok ? theme.colors.up : theme.colors.warning }}>
          {invalid ? ta.targetsInvalid
            : ok ? ta.sumOk
              : fill(sum < 100 ? ta.sumUnder : ta.sumOver, { sum: pct(sum, 1), diff: pct(Math.abs(100 - sum), 1) })}
        </p>
        <div className="flex flex-wrap gap-2">
          <button type="submit" disabled={!ok || save.isPending} className={btn.primary.className} style={btn.primary.style}>
            {save.isPending ? t.tracker.saving : ta.saveTargets}
          </button>
          {!a.targets && (
            <button type="button" onClick={() => setEditing(false)} className={btn.secondary.className} style={btn.secondary.style}>
              {t.tracker.cancel}
            </button>
          )}
          {a.targets && (
            <button type="button" onClick={onClear} disabled={save.isPending} className={btn.secondary.className} style={btn.secondary.style}>
              {ta.clearTargets}
            </button>
          )}
        </div>
      </form>
    </SectionCard>
  )
}

const PlanRow = memo(function PlanRow({ item, currency }: { item: AllocationPlan['items'][number]; currency: string }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const ta = t.insightsPage.allocation
  const { fmt } = useMoney(currency)
  return (
    <li className="py-2.5 flex flex-col gap-0.5 min-w-0" style={{ borderTop: `1px solid ${theme.colors.border}` }}>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[14px] font-semibold" style={{ color: theme.colors.text }}>{classLabel(item.class, t)}</span>
        <span className="text-[14px] font-semibold tabular-nums" style={{ color: theme.colors.text }}>{fmt(item.amount)}</span>
      </div>
      <p className="text-[12.5px] tabular-nums" style={{ color: theme.colors.textSub }}>
        {fill(ta.planLine, { now: pct(item.current_pct, 1), after: pct(item.after_pct, 1), target: pct(item.target_pct, 0) })}
      </p>
      <p className="text-[12.5px]" style={{ color: theme.colors.textSub }}>
        {item.buy.symbol ? (
          <>
            {item.buy.source === 'largest_holding' ? ta.buyLargest : ta.buyDefault}{' '}
            <Link href={`/stocks/${encodeURIComponent(item.buy.symbol)}`} className="font-semibold underline underline-offset-2"
              style={{ color: theme.colors.primary }}>{item.buy.symbol}</Link>
          </>
        ) : ta.buyYours}
      </p>
    </li>
  )
})

function DepositPlan({ a, scope }: { a: Allocation; scope: Scope }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const ta = t.insightsPage.allocation
  const [amount, setAmount] = useState<string>('1000')
  const { fmt } = useMoney(a.home_currency)
  const q = useAllocationPlan(scope, Number(amount), !!a.targets)
  const options = useMemo(() => AMOUNTS.map((v) => ({ value: v as string, label: fmt(Number(v), 0) })), [fmt])
  const plan = q.data
  const noTargets = !a.targets || (!!q.error && toHoldingsError(q.error).code === 'no_targets')
  return (
    <SectionCard title={ta.planTitle} subtitle={ta.planHelp}>
      {noTargets ? (
        <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{ta.planNoTargets}</p>
      ) : (
        <>
          <ChipGroup value={amount} options={options} onChange={setAmount} label={ta.planAmount} />
          {q.isLoading && <div className="h-24 rounded-xl animate-pulse" style={{ backgroundColor: theme.colors.surfaceAlt }} />}
          {!!q.error && !plan && <QueryError error={q.error} onRetry={() => q.refetch()} />}
          {plan && (plan.items.length === 0 ? (
            <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{ta.planOnTarget}</p>
          ) : (
            <>
              <ul>{plan.items.map((it) => <PlanRow key={it.class} item={it} currency={plan.home_currency} />)}</ul>
              {plan.unallocated > 0.005 && (
                <p className="text-[12.5px]" style={{ color: theme.colors.textSub }}>{fill(ta.planLeft, { amount: fmt(plan.unallocated) })}</p>
              )}
              <p className="text-[12px]" style={{ color: theme.colors.textHint }}>{ta.planNote}</p>
            </>
          ))}
        </>
      )}
    </SectionCard>
  )
}

/** Insights → Allocation: mix, holdings map, warnings, targets, deposit plan. */
export function AllocationTab({ scope, scoped }: { scope: Scope; scoped: boolean }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const ta = t.insightsPage.allocation
  const q = useAllocation(scope)
  const [by, setBy] = useState<'day' | 'total'>('day')
  const a = q.data
  if (q.isLoading) return <SkeletonCards heights={[140, 260, 200]} />
  if (q.error && !a) return <QueryError error={q.error} onRetry={() => q.refetch()} />
  if (!a) return null
  if (a.tiles.length === 0 && a.total_home <= 0) {
    return scoped ? <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{ta.emptyScope}</p> : <EmptyHoldings />
  }
  return (
    <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 items-start min-w-0">
      <div className="flex flex-col gap-4 min-w-0">
        <SectionCard title={ta.mixTitle}>
          <MixBar a={a} />
          <Freshness asOf={a.as_of} delayed={a.delayed_minutes} />
        </SectionCard>
        <SectionCard title={ta.mapTitle} subtitle={ta.mapHelp}
          right={<Segmented value={by} onChange={setBy} label={ta.colorBy}
            options={[{ value: 'day', label: ta.byDay }, { value: 'total', label: ta.byTotal }]} />}>
          {a.tiles.length === 0
            ? <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{ta.noTiles}</p>
            : <Treemap tiles={a.tiles} by={by} />}
          {a.unpriced.length > 0 && (
            <p className="text-[12px]" style={{ color: theme.colors.textHint }}><SymbolListText template={ta.unpriced} symbols={a.unpriced} /></p>
          )}
        </SectionCard>
        <SectionCard title={ta.warningsTitle}>
          {a.warnings.length === 0 ? (
            <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{ta.noWarnings}</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {a.warnings.map((w, i) => (
                <li key={`${w.code}-${i}`} className="flex items-start gap-2.5 rounded-xl px-3 py-2.5 text-[13px]"
                  style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.text }}>
                  <AlertTriangle size={16} aria-hidden="true" className="shrink-0 mt-0.5" style={{ color: theme.colors.warning }} />
                  <span className="min-w-0 break-words">{warningText(w, t)}</span>
                </li>
              ))}
            </ul>
          )}
        </SectionCard>
      </div>
      <div className="flex flex-col gap-4 min-w-0">
        <TargetsEditor a={a} />
        {a.targets && <DepositPlan a={a} scope={scope} />}
      </div>
    </div>
  )
}
