'use client'

import { memo, useMemo } from 'react'
import { AlertTriangle, Check, Minus, X } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore, INTL_LOCALES, type Locale } from '@/store/i18nStore'
import { Panel } from '@/components/insights/Panel'
import { DASH, fill, nativePrice, shortDate } from '@/lib/insights'
import type en from '@/lib/i18n/en.json'
import type { StockCheck, StockCheckStatus } from '@/types/stock'

type T = typeof en

const PRICE_KEYS = new Set(['price', 'sma50', 'sma200'])
const MONEY_KEYS = new Set(['dollar_volume', 'min'])

/** Compact money in the listing currency: 32_000_000 -> "C$32M". */
export function compactMoney(v: number | null | undefined, currency: string | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return DASH
  const ccy = (currency || 'USD').toUpperCase()
  const prefix = ccy === 'CAD' ? 'C$' : ccy === 'USD' ? '$' : `${ccy} `
  const abs = Math.abs(v)
  if (abs >= 1e12) return `${prefix}${(v / 1e12).toFixed(abs >= 1e13 ? 0 : 1)}T`
  if (abs >= 1e9) return `${prefix}${(v / 1e9).toFixed(abs >= 1e10 ? 0 : 1)}B`
  if (abs >= 1e6) return `${prefix}${(v / 1e6).toFixed(abs >= 1e7 ? 0 : 1)}M`
  if (abs >= 1e3) return `${prefix}${(v / 1e3).toFixed(0)}K`
  return `${prefix}${v.toFixed(0)}`
}

/** One check through t.stock.checks[key][detail_code] with its params. */
export function checkText(c: StockCheck, t: T, locale: string, symbol: string, currency: string | null): string {
  const group = (t.stock.checks as Record<string, Record<string, string>>)[c.key]
  const tpl = group?.[c.detail_code]
  if (!tpl) return DASH
  const loc = INTL_LOCALES[locale as Locale] ?? 'en-CA'
  const vars: Record<string, string | number | null> = {}
  for (const [k, v] of Object.entries(c.params ?? {})) {
    if (v === null || v === undefined || v === '') vars[k] = null
    else if (PRICE_KEYS.has(k)) vars[k] = nativePrice(Number(v), symbol, currency)
    else if (MONEY_KEYS.has(k)) vars[k] = compactMoney(Number(v), String(c.params.currency ?? currency ?? 'USD'))
    else if (k === 'date') vars[k] = shortDate(String(v), locale, true)
    else if (k === 'rating') vars[k] = (t.stock.ratings as Record<string, string>)[String(v)] ?? String(v)
    else if (typeof v === 'number') vars[k] = v.toLocaleString(loc, { maximumFractionDigits: 1 })
    else vars[k] = v
  }
  return fill(tpl, vars)
}

const StatusIcon = memo(function StatusIcon({ status, color }: { status: StockCheckStatus; color: string }) {
  const Icon = status === 'pass' ? Check : status === 'warn' ? AlertTriangle : status === 'fail' ? X : Minus
  return <Icon size={16} aria-hidden="true" style={{ color }} />
})

const CheckRow = memo(function CheckRow({ label, statusLabel, text, status, color }: {
  label: string
  statusLabel: string
  text: string
  status: StockCheckStatus
  color: string
}) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  return (
    <li
      className="rounded-[10px] p-3 flex items-start gap-3 min-w-0"
      style={{ backgroundColor: theme.colors.surfaceAlt, borderLeft: `3px solid ${color}` }}
      aria-label={fill(t.stock.checkAria, { label, status: statusLabel })}
    >
      <span className="mt-0.5 shrink-0"><StatusIcon status={status} color={color} /></span>
      <div className="flex-1 min-w-0 flex flex-col gap-0.5">
        <div className="flex items-baseline justify-between gap-2">
          <span className="text-[13.5px] font-semibold" style={{ color: theme.colors.text }}>{label}</span>
          <span className="text-[11.5px] font-semibold whitespace-nowrap" style={{ color }}>{statusLabel}</span>
        </div>
        <p className="text-[12.5px] leading-snug break-words" style={{ color: theme.colors.textSub }}>{text}</p>
      </div>
    </li>
  )
})

/** "Signa checks": rule-based facts about the stock (not advice). */
export function StockChecks({ checks, symbol, currency }: {
  checks: StockCheck[]
  symbol: string
  currency: string | null
}) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const ts = t.stock

  const rows = useMemo(() => {
    const colors: Record<StockCheckStatus, string> = {
      pass: theme.colors.up, warn: theme.colors.warning, fail: theme.colors.down, na: theme.colors.textHint,
    }
    return checks.map((c) => ({
      key: c.key,
      status: c.status,
      color: colors[c.status] ?? theme.colors.textHint,
      label: (ts.checks as Record<string, { label: string }>)[c.key]?.label ?? c.key,
      statusLabel: (ts.statusLabel as Record<string, string>)[c.status] ?? c.status,
      text: checkText(c, t, locale, symbol, currency),
    }))
  }, [checks, theme, ts, t, locale, symbol, currency])

  return (
    <Panel title={ts.checksTitle} subtitle={ts.checksSubtitle}>
      <div className="flex flex-col gap-3">
        <ul className="flex flex-col gap-2">
          {rows.map((r) => (
            <CheckRow key={r.key} label={r.label} statusLabel={r.statusLabel} text={r.text} status={r.status} color={r.color} />
          ))}
        </ul>
        <p className="text-[11.5px] leading-snug" style={{ color: theme.colors.textHint }}>{ts.disclaimer}</p>
      </div>
    </Panel>
  )
}
