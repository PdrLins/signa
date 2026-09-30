// Formatting for the "Compare" view of Check a stock. Pure.
import { DASH, fill, shortDate } from '@/lib/insights'
import { intlLocale } from '@/store/i18nStore'
import type en from '@/lib/i18n/en.json'
import type { CompareMetric } from '@/types/check'

type T = typeof en

function n(v: number, digits: number): string {
  return v.toLocaleString(intlLocale(), { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

function signedPct(v: number, digits = 1): string {
  const s = n(Math.abs(v), digits)
  return Number(v.toFixed(digits)) === 0 ? `${n(0, digits)}%` : `${v > 0 ? '+' : '−'}${s}%`
}

/** Main text for one metric cell. */
export function formatMetricValue(m: CompareMetric, sym: string, t: T): string {
  const tc = t.check
  const v = m.values[sym]
  const detail = (m.detail?.[sym] ?? null) as Record<string, unknown> | null
  if (m.key === 'recovery_days' && (v === null || v === undefined) && detail && detail.recovered === false) {
    return tc.compare.notRecovered
  }
  if (v === null || v === undefined || v === '') return DASH
  switch (m.format) {
    case 'verdict': {
      const dict = (m.key === 'verdict' && typeof v === 'string' && v in tc.long.verdict ? tc.long.verdict : tc.verdict) as Record<string, string>
      return dict[String(v)] ?? String(v)
    }
    case 'bool':
      return v ? tc.compare.pass : tc.compare.fail
    case 'signal':
      return String(v)
    case 'rating':
      return (tc.long.ratings as Record<string, string>)[String(v)] ?? String(v)
    case 'int':
      return typeof v === 'number' ? n(v, 0) : String(v)
    case 'prob':
      return typeof v === 'number' ? `${n(v * 100, 0)}%` : String(v)
    case 'ratio':
      return typeof v === 'number' ? n(v, m.key === 'rr' ? 2 : 1) : String(v)
    case 'days':
      return typeof v === 'number' ? fill(tc.compare.daysValue, { n: n(v, 0) }) : String(v)
    case 'corr':
      return typeof v === 'number' ? n(v, 2) : String(v)
    case 'pct':
      if (typeof v !== 'number') return String(v)
      if (m.key.startsWith('cagr_') || m.key === 'max_drawdown' || m.key === 'dividend_growth_5y') return signedPct(v)
      return `${n(v, m.key === 'expense_ratio' || m.key === 'dividend_yield' ? 2 : 1)}%`
    case 'date':
      return typeof v === 'string' ? shortDate(v, '', true) : String(v)
    default:
      return typeof v === 'number' ? n(v, 0) : String(v)
  }
}

/** Optional second line (benchmark, shares, correlated holding). */
export function formatMetricSub(m: CompareMetric, sym: string, t: T): string | null {
  const tc = t.check.compare
  const d = (m.detail?.[sym] ?? null) as Record<string, unknown> | null
  if (!d) return null
  if (m.key.startsWith('cagr_')) {
    const bc = d.benchmark_cagr
    return d.benchmark && typeof bc === 'number' ? fill(tc.vsBench, { bench: String(d.benchmark), cagr: signedPct(bc) }) : null
  }
  if (m.key === 'next_ex_date' && m.values[sym] != null) {
    return d.estimated ? tc.estimatedTag : null
  }
  if (m.key === 'dividend_growth_5y' && d.recent_cut) return tc.cutTag
  if (m.key === 'dividend_yield' && typeof d.frequency === 'string' && m.values[sym] != null) {
    return (t.check.dividend.frequencies as Record<string, string>)[d.frequency] ?? d.frequency
  }
  if (m.key === 'position_pct' && typeof d.shares === 'number') {
    const s = d.shares >= 10 ? n(d.shares, 0) : n(d.shares, 3)
    return fill(tc.sharesValue, { shares: s })
  }
  if (m.key === 'correlation' && m.values[sym] != null) {
    const s = (m.detail?.[sym] ?? null) as unknown
    return typeof s === 'string' && s ? fill(tc.corrWith, { symbol: s }) : null
  }
  return null
}

export function metricLabel(key: string, t: T): string {
  return (t.check.compare.metrics as Record<string, string>)[key] ?? key
}

export function isBest(m: CompareMetric, sym: string): boolean {
  return !!m.best && m.best.includes(sym)
}
