// Translate portfolio-tracker API errors ({detail: {code, message}}) into
// the user's language. Unknown codes fall back to a generic message.
import { fill } from '@/lib/insights'
import { toHoldingsError } from '@/hooks/useHoldings'
import type en from '@/lib/i18n/en.json'

type T = typeof en

export function trackerErrorCode(e: unknown): string {
  return toHoldingsError(e).code
}

export function isMigrationRequired(e: unknown): boolean {
  return !!e && trackerErrorCode(e) === 'migration_required'
}

export function trackerErrorText(e: unknown, t: T): string {
  const he = toHoldingsError(e)
  const map = t.tracker.errors as Record<string, string>
  const tpl = map[he.code] ?? t.tracker.errors.internal
  return fill(tpl, { limit: he.limit ?? null })
}

/** Money input: "1 234,50" / "1,234.50" / "1234.5" → number; '' → null; junk → NaN. */
export function parseAmount(v: string): number | null {
  const s = v.trim().replace(/\s/g, '')
  if (!s) return null
  // one comma and no dot = decimal comma (pt); otherwise commas are thousands
  const norm = /^-?\d+,\d+$/.test(s) ? s.replace(',', '.') : s.replace(/,/g, '')
  const n = Number(norm)
  return Number.isFinite(n) ? n : NaN
}
