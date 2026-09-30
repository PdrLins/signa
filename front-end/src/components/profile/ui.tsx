'use client'

import { memo, useId, type ReactNode } from 'react'
import Link from 'next/link'
import { ArrowLeft, ChevronRight, type LucideIcon } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'

/** Shared input classes/styles for tracker forms (44px, 16px on phones). */
export function useFieldStyle() {
  const theme = useTheme()
  return {
    input: 'min-h-[44px] rounded-lg px-3 text-[16px] md:text-[14px] w-full min-w-0 focus-visible:outline focus-visible:outline-2',
    style: {
      backgroundColor: theme.colors.surfaceAlt,
      border: `1px solid ${theme.colors.border}`,
      color: theme.colors.text,
      outlineColor: theme.colors.primary,
    },
    label: 'flex flex-col gap-1 min-w-0 text-[12px]',
    labelColor: theme.colors.textSub,
  }
}

export function useButtonStyles() {
  const theme = useTheme()
  const base = 'min-h-[44px] px-4 rounded-xl text-[14px] font-semibold disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 inline-flex items-center justify-center gap-2'
  return {
    primary: { className: base, style: { backgroundColor: theme.colors.primary, color: theme.colors.surface, outlineColor: theme.colors.primary } },
    secondary: { className: base.replace('font-semibold', 'font-medium'), style: { backgroundColor: theme.colors.surfaceAlt, color: theme.colors.text, outlineColor: theme.colors.primary } },
    danger: { className: base, style: { backgroundColor: theme.colors.surfaceAlt, color: theme.colors.down, outlineColor: theme.colors.primary } },
    icon: {
      className: 'min-h-[44px] min-w-[44px] rounded-lg inline-flex items-center justify-center focus-visible:outline focus-visible:outline-2 disabled:opacity-50',
      style: { color: theme.colors.textSub, outlineColor: theme.colors.primary },
    },
  }
}

/** Titled card section. */
export function SectionCard({ title, subtitle, right, children }: {
  title: ReactNode
  subtitle?: ReactNode
  right?: ReactNode
  children: ReactNode
}) {
  const theme = useTheme()
  const id = useId()
  return (
    <section aria-labelledby={id} className="rounded-2xl p-4 md:p-5 flex flex-col gap-3 min-w-0"
      style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.border}` }}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="min-w-0">
          <h2 id={id} className="text-[16px] md:text-[17px] font-semibold" style={{ color: theme.colors.text }}>{title}</h2>
          {subtitle && <p className="text-[13px] mt-0.5" style={{ color: theme.colors.textSub }}>{subtitle}</p>}
        </div>
        {right}
      </div>
      {children}
    </section>
  )
}

/** A row that links onward (chevron on the right). */
export const LinkRow = memo(function LinkRow({ href, icon: Icon, label, desc, badge }: {
  href: string
  icon: LucideIcon
  label: string
  desc?: string
  badge?: string
}) {
  const theme = useTheme()
  return (
    <Link href={href}
      className="flex items-center gap-3 rounded-xl px-3 py-2.5 min-h-[44px] transition-opacity hover:opacity-90 focus-visible:outline focus-visible:outline-2"
      style={{ backgroundColor: theme.colors.surfaceAlt, outlineColor: theme.colors.primary }}>
      <Icon size={18} aria-hidden="true" style={{ color: theme.colors.primary }} />
      <span className="min-w-0 flex-1">
        <span className="block text-[14px] font-medium" style={{ color: theme.colors.text }}>{label}</span>
        {desc && <span className="block text-[12px] mt-0.5" style={{ color: theme.colors.textSub }}>{desc}</span>}
      </span>
      {badge && <SoonBadge label={badge} />}
      <ChevronRight size={16} aria-hidden="true" style={{ color: theme.colors.textSub }} />
    </Link>
  )
})

/** A non-link row for things that aren't built yet ("Coming soon"). */
export function StaticRow({ icon: Icon, label, desc, badge }: {
  icon: LucideIcon
  label: string
  desc?: string
  badge?: string
}) {
  const theme = useTheme()
  return (
    <div className="flex items-center gap-3 rounded-xl px-3 py-2.5 min-h-[44px]" style={{ backgroundColor: theme.colors.surfaceAlt }}>
      <Icon size={18} aria-hidden="true" style={{ color: theme.colors.textSub }} />
      <span className="min-w-0 flex-1">
        <span className="block text-[14px] font-medium" style={{ color: theme.colors.text }}>{label}</span>
        {desc && <span className="block text-[12px] mt-0.5" style={{ color: theme.colors.textSub }}>{desc}</span>}
      </span>
      {badge && <SoonBadge label={badge} />}
    </div>
  )
}

export function SoonBadge({ label, tone = 'hint' }: { label: string; tone?: 'hint' | 'primary' }) {
  const theme = useTheme()
  const color = tone === 'primary' ? theme.colors.primary : theme.colors.textSub
  return (
    <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full whitespace-nowrap shrink-0"
      style={{ color, border: `1px solid ${theme.colors.border}` }}>
      {label}
    </span>
  )
}

/** On/off switch with a visible label and optional description. */
export function ToggleRow({ checked, onChange, label, desc, disabled }: {
  checked: boolean
  onChange: (v: boolean) => void
  label: string
  desc?: string
  disabled?: boolean
}) {
  const theme = useTheme()
  const id = useId()
  return (
    <div className="flex items-center justify-between gap-3 min-h-[44px]">
      <div className="min-w-0">
        <p id={id} className="text-[14px] font-medium" style={{ color: theme.colors.text }}>{label}</p>
        {desc && <p className="text-[12px] mt-0.5" style={{ color: theme.colors.textSub }}>{desc}</p>}
      </div>
      <button type="button" role="switch" aria-checked={checked} aria-labelledby={id} disabled={disabled}
        onClick={() => onChange(!checked)}
        className="shrink-0 min-h-[44px] min-w-[52px] flex items-center justify-center rounded-full disabled:opacity-50 focus-visible:outline focus-visible:outline-2"
        style={{ outlineColor: theme.colors.primary }}>
        <span className="relative w-11 h-6 rounded-full transition-colors"
          style={{ backgroundColor: checked ? theme.colors.primary : theme.colors.border }}>
          <span className="absolute top-0.5 w-5 h-5 rounded-full transition-all"
            style={{ left: checked ? 22 : 2, backgroundColor: theme.colors.surface }} />
        </span>
      </button>
    </div>
  )
}

/** Segmented choice (radio group of buttons). */
export function Segmented<V extends string>({ value, options, onChange, label, disabled }: {
  value: V
  options: { value: V; label: string }[]
  onChange: (v: V) => void
  label: string
  disabled?: boolean
}) {
  const theme = useTheme()
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex flex-wrap gap-1 p-1 rounded-xl"
      style={{ backgroundColor: theme.colors.surfaceAlt, border: `1px solid ${theme.colors.border}` }}>
      {options.map((o) => {
        const on = o.value === value
        return (
          <button key={o.value} type="button" role="radio" aria-checked={on} disabled={disabled}
            onClick={() => onChange(o.value)}
            className="min-h-[44px] px-3 rounded-lg text-[13px] font-medium disabled:opacity-50 focus-visible:outline focus-visible:outline-2"
            style={{
              backgroundColor: on ? theme.colors.surface : 'transparent',
              color: on ? theme.colors.text : theme.colors.textSub,
              outlineColor: theme.colors.primary,
            }}>
            {o.label}
          </button>
        )
      })}
    </div>
  )
}

/** Page title with an optional back link (to /profile). */
export function TrackerHeader({ title, subtitle, backHref, backLabel, right }: {
  title: string
  subtitle?: string
  backHref?: string
  backLabel?: string
  right?: ReactNode
}) {
  const theme = useTheme()
  return (
    <header className="flex flex-col gap-2 min-w-0">
      {backHref && (
        <Link href={backHref} aria-label={backLabel}
          className="self-start -ml-2 min-h-[44px] px-2 inline-flex items-center gap-1.5 rounded-lg text-[13px] font-medium focus-visible:outline focus-visible:outline-2"
          style={{ color: theme.colors.textSub, outlineColor: theme.colors.primary }}>
          <ArrowLeft size={16} aria-hidden="true" />{backLabel}
        </Link>
      )}
      <div className="flex flex-wrap items-end justify-between gap-3 min-w-0">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold" style={{ color: theme.colors.text }}>{title}</h1>
          {subtitle && <p className="text-[13px] md:text-sm mt-1 max-w-2xl" style={{ color: theme.colors.textSub }}>{subtitle}</p>}
        </div>
        {right}
      </div>
    </header>
  )
}

/** Friendly notice for 503 migration_required (the tracker's tables aren't there yet). */
export function MigrationNotice() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  return (
    <section role="status" className="rounded-2xl p-5" style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.border}` }}>
      <h2 className="text-[16px] font-semibold" style={{ color: theme.colors.text }}>{t.tracker.migrationTitle}</h2>
      <p className="text-[13px] mt-1" style={{ color: theme.colors.textSub }}>{t.tracker.migrationBody}</p>
    </section>
  )
}

/** Load error with retry. */
export function LoadError({ message, onRetry }: { message: string; onRetry?: () => void }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  return (
    <div role="alert" className="rounded-2xl p-4 flex flex-wrap items-center justify-between gap-3 text-[14px]"
      style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.down}`, color: theme.colors.text }}>
      <span>{message}</span>
      {onRetry && (
        <button type="button" onClick={onRetry}
          className="min-h-[44px] px-4 rounded-xl text-[14px] font-medium focus-visible:outline focus-visible:outline-2"
          style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.text, outlineColor: theme.colors.primary }}>
          {t.tracker.retry}
        </button>
      )}
    </div>
  )
}

/** "Coming soon" placeholder card. */
export const SoonCard = memo(function SoonCard({ title, body, icon: Icon }: { title: string; body: string; icon?: LucideIcon }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  return (
    <li className="rounded-2xl p-4 flex flex-col gap-2 min-w-0"
      style={{ backgroundColor: theme.colors.surface, border: `1px dashed ${theme.colors.border}` }}>
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-[15px] font-semibold flex items-center gap-2" style={{ color: theme.colors.text }}>
          {Icon && <Icon size={16} aria-hidden="true" style={{ color: theme.colors.primary }} />}{title}
        </h2>
        <SoonBadge label={t.tracker.comingSoon} />
      </div>
      <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{body}</p>
    </li>
  )
})
