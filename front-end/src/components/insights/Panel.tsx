'use client'

import { useId } from 'react'
import { useTheme } from '@/hooks/useTheme'
import { cn } from '@/lib/utils'

/** Titled card section (h2 + optional right-hand slot) used by the
 *  Today / Is it working? / decision-trail pages. */
export function Panel({ title, subtitle, right, children, className, bodyClassName, padded = true }: {
  title?: React.ReactNode
  subtitle?: React.ReactNode
  right?: React.ReactNode
  children: React.ReactNode
  className?: string
  bodyClassName?: string
  padded?: boolean
}) {
  const theme = useTheme()
  const id = useId()
  return (
    <section
      aria-labelledby={title ? id : undefined}
      className={cn('rounded-2xl flex flex-col min-w-0', padded ? 'p-5 md:p-6' : 'py-5 md:py-6', className)}
      style={{
        backgroundColor: theme.colors.surface,
        border: `1px solid ${theme.colors.border}`,
        boxShadow: theme.isDark ? '0 2px 10px rgba(0,0,0,0.3)' : '0 2px 10px rgba(0,0,0,0.06)',
      }}
    >
      {(title || right) && (
        <div className={cn('flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 mb-4', !padded && 'px-5 md:px-6')}>
          <div className="min-w-0 flex flex-col gap-1">
            {title && (
              <h2 id={id} className="text-[16px] md:text-[17px] font-semibold" style={{ color: theme.colors.text }}>
                {title}
              </h2>
            )}
            {subtitle && <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{subtitle}</p>}
          </div>
          {right}
        </div>
      )}
      <div className={cn('min-w-0', bodyClassName)}>{children}</div>
    </section>
  )
}

/** Small uppercase-free label + mono value tile. */
export function StatTile({ label, value, sub, valueColor }: {
  label: React.ReactNode
  value: React.ReactNode
  sub?: React.ReactNode
  valueColor?: string
}) {
  const theme = useTheme()
  return (
    <div
      className="rounded-[14px] p-3.5 md:p-[18px] flex flex-col gap-1.5 md:gap-2 min-w-0"
      style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.border}` }}
    >
      <span className="text-[12px]" style={{ color: theme.colors.textSub }}>{label}</span>
      <span
        className="text-[19px] md:text-[24px] font-medium tabular-nums truncate"
        style={{ color: valueColor ?? theme.colors.text, fontFamily: 'var(--font-mono)' }}
      >
        {value}
      </span>
      {sub && <span className="text-[12px] leading-snug" style={{ color: theme.colors.textSub }}>{sub}</span>}
    </div>
  )
}

/** "not enough data (n=x/30)" pill — used wherever a stat is below threshold. */
export function NotEnough({ n, needed, label }: { n: number; needed: number; label: string }) {
  const theme = useTheme()
  return (
    <span
      className="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold tabular-nums"
      style={{ color: theme.colors.warning, border: `1px solid ${theme.colors.warning}59` }}
    >
      {label.replace('{n}', String(n)).replace('{needed}', String(needed))}
    </span>
  )
}

export const mono: React.CSSProperties = { fontFamily: 'var(--font-mono)' }
