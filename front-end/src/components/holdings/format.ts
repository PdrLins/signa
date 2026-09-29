// Formatting + chip builders for My holdings. Pure (plus theme hooks).
import { useTheme } from '@/hooks/useTheme'
import { DASH, fill } from '@/lib/insights'
import { pct, spct } from '@/components/check/long/format'
import type en from '@/lib/i18n/en.json'
import type { AllocateFactor, AllocateNote, Holding, LongVerdictCode } from '@/types/holdings'

type T = typeof en

const LOCALES: Record<string, string> = { en: 'en-CA', pt: 'pt-BR' }

/** "C$1,234.56" / "US$12.30" — the currency is always explicit. */
export function money(v: number | null | undefined, currency: string | null | undefined, locale = 'en', digits = 2): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return DASH
  const ccy = (currency || '').toUpperCase()
  const prefix = ccy === 'CAD' ? 'C$' : ccy === 'USD' ? 'US$' : ccy ? `${ccy} ` : '$'
  const n = Math.abs(v).toLocaleString(LOCALES[locale] ?? 'en-CA', { minimumFractionDigits: digits, maximumFractionDigits: digits })
  return `${v < 0 ? '−' : ''}${prefix}${n}`
}

export function num(v: number | null | undefined, locale = 'en', maxDigits = 4): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return DASH
  return v.toLocaleString(LOCALES[locale] ?? 'en-CA', { maximumFractionDigits: maxDigits })
}

export { pct, spct }

export type Tone = 'up' | 'down' | 'warning' | 'neutral' | 'primary'

export function useToneColor() {
  const theme = useTheme()
  return (tone: Tone) =>
    tone === 'up' ? theme.colors.up
      : tone === 'down' ? theme.colors.down
        : tone === 'warning' ? theme.colors.warning
          : tone === 'primary' ? theme.colors.primary
            : theme.colors.textSub
}

export function verdictTone(v: LongVerdictCode | null | undefined): Tone {
  return v === 'SOLID' ? 'up' : v === 'REASONABLE_WITH_CAVEATS' ? 'warning' : v === 'NOT_A_GOOD_FIT' ? 'down' : 'neutral'
}

export interface Chip {
  key: string
  label: string
  tone: Tone
  title?: string
}

/** Status chips for one holding: trend, earnings, red flags, overweight, fund structure. */
export function holdingChips(h: Holding, th: T['holdings'], maxWeight: number): Chip[] {
  const st = h.holding_status || {}
  const chips: Chip[] = []
  if (st.price != null || st.trend) {
    const trend = st.trend ?? 'unknown'
    if (trend === 'ok') chips.push({ key: 'trend', label: th.chips.trendOk, tone: 'up', title: th.chips.trendOkHelp })
    else if (trend === 'weak') chips.push({ key: 'trend', label: th.chips.trendWeak, tone: 'warning', title: th.chips.trendWeakHelp })
    else if (trend === 'break') chips.push({ key: 'trend', label: th.chips.trendBreak, tone: 'down', title: fill(th.chips.trendBreakHelp, { pct: spct(st.pct_vs_sma200, 1) }) })
    else chips.push({ key: 'trend', label: th.chips.trendUnknown, tone: 'neutral' })
  }
  const e = st.earnings
  if (e && e.days !== null && e.days !== undefined && e.days >= 0 && e.days <= 14) {
    chips.push({
      key: 'earnings',
      label: e.days === 0 ? th.chips.earningsToday : fill(th.chips.earnings, { n: e.days }),
      tone: e.days <= 7 ? 'warning' : 'neutral',
      title: e.date ?? undefined,
    })
  }
  const flags = st.red_flags ?? []
  if (flags.length) {
    chips.push({ key: 'flag', label: flags.length > 1 ? fill(th.chips.redFlags, { n: flags.length }) : th.chips.redFlag, tone: 'down', title: flags[0]?.text })
  }
  if (h.position?.overweight) {
    chips.push({ key: 'ow', label: th.chips.overweight, tone: 'down',
      title: fill(th.chips.overweightHelp, { w: pct(h.position.weight_pct, 1), max: pct(maxWeight, 0) }) })
  }
  if (h.flags?.leveraged) chips.push({ key: 'lev', label: th.chips.leveraged, tone: 'warning' })
  if (h.flags?.covered_call) chips.push({ key: 'cc', label: th.chips.coveredCall, tone: 'neutral' })
  if (h.flags?.cash_like) chips.push({ key: 'cash', label: th.chips.cashLike, tone: 'neutral' })
  return chips
}

function factorVars(f: AllocateFactor): Record<string, string | number | null> {
  const p = f.params || {}
  const n = (k: string) => (typeof p[k] === 'number' ? (p[k] as number) : null)
  return {
    drawdown_pct: n('drawdown_pct') !== null ? spct(n('drawdown_pct'), 0) : null,
    pct_vs_sma200: n('pct_vs_sma200') !== null ? pct(Math.abs(n('pct_vs_sma200') as number), 0) : null,
    weight_pct: n('weight_pct') !== null ? pct(n('weight_pct'), 0) : null,
    max_pct: n('max_pct') !== null ? pct(n('max_pct'), 0) : null,
    days: n('days'),
  }
}

export function factorText(f: AllocateFactor, th: T['holdings']): string {
  const tpl = (th.allocate.factors as Record<string, string>)[f.code]
  return tpl ? fill(tpl, factorVars(f)) : f.code.replace(/_/g, ' ')
}

/** One-line reason: the two factors that moved the rank most. */
export function ideaReason(factors: AllocateFactor[], th: T['holdings']): string {
  const top = factors.filter((f) => f.points !== 0).slice(0, 2)
  const use = top.length ? top : factors.slice(0, 1)
  const s = use.map((f) => factorText(f, th)).join('; ')
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : ''
}

export function noteText(n: AllocateNote, th: T['holdings']): string {
  const tpl = (th.allocate.notes as Record<string, string>)[n.code]
  return tpl ? fill(tpl, { symbols: n.symbols.join(', ') }) : n.text
}

export function errorText(code: string, th: T['holdings'], vars: Record<string, string | number | null> = {}): string {
  const tpl = (th.errors as Record<string, string>)[code] ?? th.errors.internal
  return fill(tpl, vars)
}
