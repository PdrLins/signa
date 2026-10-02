'use client'

import Link from 'next/link'
import { Moon, Sparkles, Sunrise } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { etTime, signedPct } from '@/lib/insights'
import { arrow, useSignColor } from '@/components/tracker/ui'

/** "After hours ↓C$120.00 −0.04% · 7:55 PM" (Premium, migration 021) or,
 *  for Free while US stocks trade pre/after hours, a link to the plans.
 *  `amount` is already formatted (portfolio change or a stock's price). */
export function ExtendedLine({ session, amount, value, pct, asOf, locked, size = 'md' }: {
  session?: 'pre' | 'post' | null
  /** formatted money (portfolio: signed change; stock: the price) */
  amount?: string | null
  /** sign source for the colour / arrow (portfolio change, or pct for a price) */
  value?: number | null
  pct?: number | null
  asOf?: string | null
  locked?: boolean
  size?: 'sm' | 'md'
}) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const te = t.trackerUi.extended
  const signColor = useSignColor()
  const text = size === 'sm' ? 'text-[12px]' : 'text-[13px]'

  if (locked) {
    return (
      <Link href="/pricing" onClick={(e) => e.stopPropagation()}
        className={`${text} inline-flex items-center gap-1.5 font-medium rounded focus-visible:outline focus-visible:outline-2`}
        style={{ color: theme.colors.primary, outlineColor: theme.colors.primary }}>
        <Sparkles size={13} aria-hidden="true" />{te.locked}
      </Link>
    )
  }
  if (!session) return null
  const label = session === 'pre' ? te.pre : te.post
  const Icon = session === 'pre' ? Sunrise : Moon
  const sign = value ?? pct ?? null
  return (
    <p className={`${text} tabular-nums flex flex-wrap items-center gap-x-1.5`} style={{ color: theme.colors.textSub }}>
      <Icon size={13} aria-hidden="true" />
      <span>{label}</span>
      <span className="font-semibold" style={{ color: signColor(sign) }}>
        {amount ? `${value !== undefined && value !== null ? arrow(value) : ''}${amount}` : ''}{pct != null ? ` ${signedPct(pct)}` : ''}
      </span>
      {asOf && <span style={{ color: theme.colors.textHint }}>· {etTime(asOf, locale)}</span>}
    </p>
  )
}
