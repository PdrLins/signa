'use client'

import { memo, useEffect, useId, useRef, useState, type ReactNode } from 'react'
import Link from 'next/link'
import { Eye, EyeOff, Landmark, Plus, Sparkles } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { usePrivacyStore } from '@/store/privacyStore'
import { useAccess } from '@/hooks/useAccess'
import { useAccounts, usePeople } from '@/hooks/useAccounts'
import { toHoldingsError } from '@/hooks/useHoldings'
import { ApiAccessError } from '@/lib/access'
import { etTime, fill } from '@/lib/insights'
import { trackerErrorText } from '@/lib/trackerErrors'
import { LoadError, MigrationNotice, SoonBadge, useButtonStyles } from '@/components/profile/ui'
import type { SafetyGrade, Scope } from '@/types/tracker'

/** Eye toggle: hides money values on this device (localStorage, try/catch). */
export function HideAmountsButton() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const hidden = usePrivacyStore((s) => s.hidden)
  const toggle = usePrivacyStore((s) => s.toggle)
  const load = usePrivacyStore((s) => s.load)
  useEffect(() => { load() }, [load])
  const label = hidden ? t.trackerUi.showAmounts : t.trackerUi.hideAmounts
  return (
    <button type="button" onClick={toggle} aria-pressed={hidden} aria-label={label} title={label}
      className="min-h-[44px] min-w-[44px] rounded-full inline-flex items-center justify-center focus-visible:outline focus-visible:outline-2"
      style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.text, outlineColor: theme.colors.primary }}>
      {hidden ? <EyeOff size={18} aria-hidden="true" /> : <Eye size={18} aria-hidden="true" />}
    </button>
  )
}

/** "All" / one person / one account — the value lives in the URL. Hidden
 *  when the user has no accounts (or accounts aren't available yet). */
export function ScopeSelect({ scope, onChange }: { scope: Scope; onChange: (s: Scope) => void }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const ts = t.trackerUi.scope
  const id = useId()
  const accounts = useAccounts()
  const people = usePeople()
  const accs = accounts.data?.items ?? []
  const ppl = (people.data?.items ?? []).filter((p) => p.accounts_count > 0)
  if (accs.length === 0) return null
  const value = scope.account_id ? `a:${scope.account_id}` : scope.person_id ? `p:${scope.person_id}` : ''
  return (
    <div className="flex items-center gap-2 min-w-0">
      <label htmlFor={id} className="text-[13px] shrink-0" style={{ color: theme.colors.textSub }}>{ts.label}</label>
      <select id={id} value={value} aria-label={ts.label}
        onChange={(e) => {
          const v = e.target.value
          onChange(v.startsWith('a:') ? { account_id: v.slice(2) } : v.startsWith('p:') ? { person_id: v.slice(2) } : {})
        }}
        className="min-h-[44px] rounded-xl px-3 text-[16px] md:text-[14px] min-w-0 max-w-full flex-1 sm:flex-none focus-visible:outline focus-visible:outline-2"
        style={{ backgroundColor: theme.colors.surfaceAlt, border: `1px solid ${theme.colors.border}`, color: theme.colors.text, outlineColor: theme.colors.primary }}>
        <option value="">{ts.all}</option>
        {ppl.length > 1 && (
          <optgroup label={ts.people}>
            {ppl.map((p) => <option key={p.id} value={`p:${p.id}`}>{p.name}</option>)}
          </optgroup>
        )}
        <optgroup label={ts.accounts}>
          {accs.map((a) => <option key={a.id} value={`a:${a.id}`}>{a.name}</option>)}
        </optgroup>
      </select>
    </div>
  )
}

/** Pill chips acting as one radio group (44px targets). */
export function ChipGroup<V extends string>({ value, options, onChange, label, activeColor }: {
  value: V
  options: { value: V; label: string; title?: string }[]
  onChange: (v: V) => void
  label: string
  /** colour of the selected chip (defaults to primary) */
  activeColor?: string
}) {
  const theme = useTheme()
  const on = activeColor ?? theme.colors.primary
  return (
    <div role="radiogroup" aria-label={label} className="flex gap-1.5 overflow-x-auto min-w-0 pb-1 -mb-1">
      {options.map((o) => {
        const sel = o.value === value
        return (
          <button key={o.value} type="button" role="radio" aria-checked={sel} title={o.title} onClick={() => onChange(o.value)}
            className="min-h-[44px] min-w-[44px] px-3 rounded-full text-[13px] font-semibold whitespace-nowrap tabular-nums focus-visible:outline focus-visible:outline-2"
            style={{
              backgroundColor: sel ? on + '26' : 'transparent',
              color: sel ? on : theme.colors.textSub,
              border: `1px solid ${sel ? on : theme.colors.border}`,
              outlineColor: theme.colors.primary,
            }}>
            {o.label}
          </button>
        )
      })}
    </div>
  )
}

/** "As of 10:42 ET · delayed 15 min". */
export function Freshness({ asOf, delayed }: { asOf: string | null | undefined; delayed: number | null | undefined }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  if (!asOf) return null
  return (
    <p className="text-[12px] tabular-nums" style={{ color: theme.colors.textHint }} aria-live="polite">
      {fill(delayed ? t.trackerUi.asOfDelayed : t.trackerUi.asOf, { time: etTime(asOf, locale), min: delayed ?? 0 })}
    </p>
  )
}

/** Small "Premium" call-out for a 403 upgrade_required. */
export function PremiumHint({ body }: { body?: string }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  return (
    <div role="status" className="rounded-2xl p-4 flex items-start gap-3 min-w-0"
      style={{ backgroundColor: theme.colors.surfaceAlt, border: `1px solid ${theme.colors.border}` }}>
      <Sparkles size={18} aria-hidden="true" className="shrink-0 mt-0.5" style={{ color: theme.colors.primary }} />
      <div className="min-w-0 flex flex-col items-start gap-1">
        <SoonBadge label={t.tracker.premium} tone="primary" />
        <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{body ?? t.trackerUi.premiumBody}</p>
        <Link href="/pricing" className="self-start min-h-[36px] inline-flex items-center text-[13px] font-medium rounded focus-visible:outline focus-visible:outline-2"
          style={{ color: theme.colors.primary, outlineColor: theme.colors.primary }}>
          {t.pricing.seePlans}
        </Link>
      </div>
    </div>
  )
}

export function isUpgrade(e: unknown): boolean {
  return e instanceof ApiAccessError && e.code === 'upgrade_required'
}

/** Error block for a failed tracker query: 503 migration → "Almost ready",
 *  403 → Premium hint, else a translated error with retry. */
export function QueryError({ error, onRetry, premiumBody }: { error: unknown; onRetry?: () => void; premiumBody?: string }) {
  const t = useI18nStore((s) => s.t)
  const code = toHoldingsError(error).code
  if (code === 'migration_required') return <MigrationNotice />
  if (isUpgrade(error)) return <PremiumHint body={premiumBody} />
  return <LoadError message={trackerErrorText(error, t)} onRetry={onRetry} />
}

/** No holdings yet → add a stock / set up accounts. */
export function EmptyHoldings({ body }: { body?: string }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const te = t.trackerUi.empty
  const btn = useButtonStyles()
  const { can } = useAccess()
  return (
    <section aria-labelledby="tracker-empty" className="rounded-2xl p-5 flex flex-col items-start gap-3"
      style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.border}` }}>
      <h2 id="tracker-empty" className="text-[17px] font-semibold" style={{ color: theme.colors.text }}>{te.title}</h2>
      <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{body ?? te.body}</p>
      <div className="flex flex-wrap gap-2">
        {can('area.holdings') && (
          <Link href="/holdings" className={btn.primary.className} style={btn.primary.style}>
            <Plus size={16} aria-hidden="true" />{te.addStock}
          </Link>
        )}
        {can('area.profile') && (
          <Link href="/profile/accounts" className={btn.secondary.className} style={btn.secondary.style}>
            <Landmark size={16} aria-hidden="true" />{te.accounts}
          </Link>
        )}
      </div>
    </section>
  )
}

/** A value that briefly highlights when it changes (live prices); no layout shift. */
export function LiveValue({ value, children, className, style }: {
  value: string
  children: ReactNode
  className?: string
  style?: React.CSSProperties
}) {
  const theme = useTheme()
  const prev = useRef(value)
  const [flash, setFlash] = useState(false)
  useEffect(() => {
    if (prev.current === value) return
    prev.current = value
    setFlash(true)
    const id = setTimeout(() => setFlash(false), 900)
    return () => clearTimeout(id)
  }, [value])
  return (
    <span className={`tabular-nums rounded-md transition-colors duration-700 ${className ?? ''}`}
      style={{ ...style, backgroundColor: flash ? theme.colors.primary + '22' : 'transparent' }}>
      {children}
    </span>
  )
}

/** Safety grade chip for a dividend payer. */
export const SafetyChip = memo(function SafetyChip({ grade }: { grade: SafetyGrade | null }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const labels = t.trackerUi.safety as Record<string, string>
  const color = grade === 'growing' || grade === 'steady' ? theme.colors.up
    : grade === 'variable' ? theme.colors.textSub
      : grade === 'watch' ? theme.colors.warning
        : grade === 'cut' ? theme.colors.down : theme.colors.textHint
  return (
    <span className="inline-block text-[11px] font-semibold px-2 py-0.5 rounded-full whitespace-nowrap"
      title={t.trackerUi.safetyHelp}
      style={{ color, border: `1px solid ${color}` }}>
      {labels[grade ?? 'unknown'] ?? labels.unknown}
    </span>
  )
})

/** Small labelled stat. */
export const Stat = memo(function Stat({ label, value, sub, color }: { label: string; value: ReactNode; sub?: ReactNode; color?: string }) {
  const theme = useTheme()
  return (
    <div className="rounded-xl p-3 min-w-0 flex flex-col gap-0.5" style={{ backgroundColor: theme.colors.surfaceAlt }}>
      <span className="text-[12px]" style={{ color: theme.colors.textSub }}>{label}</span>
      <span className="text-[17px] font-semibold tabular-nums truncate" style={{ color: color ?? theme.colors.text }}>{value}</span>
      {sub && <span className="text-[11.5px]" style={{ color: theme.colors.textHint }}>{sub}</span>}
    </div>
  )
})

/** Card skeleton list. */
export function SkeletonCards({ heights }: { heights: number[] }) {
  const theme = useTheme()
  return (
    <div className="space-y-3" aria-busy="true">
      {heights.map((h, i) => (
        <div key={i} className="rounded-2xl animate-pulse" style={{ height: h, backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.border}` }} />
      ))}
    </div>
  )
}

/** Sign → theme colour (≥ 0 up, < 0 down, null → sub text). */
export function useSignColor() {
  const theme = useTheme()
  return (v: number | null | undefined) =>
    v === null || v === undefined || !Number.isFinite(v) ? theme.colors.textSub : v >= 0 ? theme.colors.up : theme.colors.down
}

/** "↑" / "↓" arrow for a signed value. */
export function arrow(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return ''
  return v >= 0 ? '↑ ' : '↓ '
}
