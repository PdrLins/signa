// Formatting for the long-term "Check a stock" view. Pure (plus a theme hook).
import { AlertTriangle, CheckCircle2, XCircle } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { DASH, fill } from '@/lib/insights'
import type en from '@/lib/i18n/en.json'
import type { CheckText, LongVerdict, Rating, ScorecardItem } from '@/types/check'

type T = typeof en

export function useLongVerdictStyle() {
  const theme = useTheme()
  return (v: LongVerdict) =>
    v === 'SOLID' ? { color: theme.colors.up, Icon: CheckCircle2 }
      : v === 'REASONABLE_WITH_CAVEATS' ? { color: theme.colors.warning, Icon: AlertTriangle }
        : { color: theme.colors.down, Icon: XCircle }
}

export function useRatingColor() {
  const theme = useTheme()
  return (r: Rating) =>
    r === 'good' ? theme.colors.up
      : r === 'fair' ? theme.colors.warning
        : r === 'poor' ? theme.colors.down
          : theme.colors.textHint
}

/** Percent number -> "12.3%" (no sign). */
export function pct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return DASH
  return `${v.toFixed(digits)}%`
}

/** Signed percent number -> "+12.3%" / "−4.0%". */
export function spct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return DASH
  const r = Number(v.toFixed(digits))
  if (r === 0) return `${(0).toFixed(digits)}%`
  return `${r > 0 ? '+' : '−'}${Math.abs(r).toFixed(digits)}%`
}

/** Signed percentage points: "+0.4" / "−1.2". */
export function spp(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return DASH
  const r = Number(v.toFixed(digits))
  if (r === 0) return (0).toFixed(digits)
  return `${r > 0 ? '+' : '−'}${Math.abs(r).toFixed(digits)}`
}

export function fixed(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return DASH
  return v.toFixed(digits)
}

/** Compact amount in the asset's currency: 22_072_700_928 -> "C$22.1B". */
export function compactMoney(v: number | null | undefined, currency?: string | null): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return DASH
  const sym = currency === 'CAD' ? 'C$' : currency && currency !== 'USD' ? `${currency} ` : '$'
  const abs = Math.abs(v)
  if (abs >= 1e12) return `${sym}${(v / 1e12).toFixed(2)}T`
  if (abs >= 1e9) return `${sym}${(v / 1e9).toFixed(1)}B`
  if (abs >= 1e6) return `${sym}${(v / 1e6).toFixed(1)}M`
  return `${sym}${v.toLocaleString('en-US', { maximumFractionDigits: 0 })}`
}

/** "5y" -> localized "5y" / "5a". */
export function periodLabel(years: number | string | null | undefined, t: T): string {
  const n = typeof years === 'string' ? parseInt(years, 10) : years
  return n != null && Number.isFinite(n) ? fill(t.check.long.periodValue, { years: n }) : DASH
}

const PARAM_FORMAT: Record<string, (v: number) => string> = {
  expense_ratio: (v) => v.toFixed(2),
  top10: (v) => v.toFixed(0),
  cagr: (v) => v.toFixed(1),
  benchmark_cagr: (v) => v.toFixed(1),
  excess: (v) => spp(v),
  pe: (v) => v.toFixed(1),
  fcf_yield: (v) => v.toFixed(1),
  max_drawdown: (v) => v.toFixed(0).replace('-', '−'),
  volatility: (v) => v.toFixed(0),
  roe: (v) => v.toFixed(0),
  operating_margin: (v) => v.toFixed(0),
  debt_to_equity: (v) => (v / 100).toFixed(1),
  current_ratio: (v) => v.toFixed(1),
}

/** Scorecard reason through t.check.long.reasons[key][code]; falls back to
 *  the back-end's English text for unknown codes. */
export function scorecardReason(item: ScorecardItem, t: T): string {
  const group = (t.check.long.reasons as Record<string, Record<string, string>>)[item.key]
  const tpl = group?.[item.code]
  if (!tpl) return item.reason
  const vars: Record<string, string | number | null> = {}
  for (const [k, v] of Object.entries(item.params ?? {})) {
    if (v === null || v === undefined || v === '') vars[k] = null
    else if (k === 'period') vars[k] = periodLabel(String(v), t)
    else if (typeof v === 'number' && PARAM_FORMAT[k]) vars[k] = PARAM_FORMAT[k](v)
    else vars[k] = v
  }
  return fill(tpl, vars)
}

/** notes / caveats from the long-term result through t.check.long.<group>. */
export function longText(item: CheckText, group: 'notes' | 'caveats', t: T): string {
  const tpl = (t.check.long[group] as Record<string, string>)[item.code]
  return tpl ? fill(tpl, item.params ?? {}) : item.text
}
