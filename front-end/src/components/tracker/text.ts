// Pure text builders for the tracker insights pages.
import { fill } from '@/lib/insights'
import { pct } from '@/components/holdings/format'
import type en from '@/lib/i18n/en.json'
import type { AllocClass, AllocationWarning } from '@/types/tracker'

type T = typeof en

export function className(c: AllocClass | string, t: T): string {
  return (t.trackerUi.classes as Record<string, string>)[c] ?? c
}

/** Allocation warning → one translated sentence. */
export function warningText(w: AllocationWarning, t: T): string {
  const tpl = (t.trackerUi.warnings as Record<string, string>)[w.code]
  if (!tpl) return w.code
  const p = w.params || {}
  return fill(tpl, {
    pct: p.pct != null ? pct(p.pct, 0) : null,
    limit: p.limit != null ? pct(p.limit, 0) : null,
    symbol: p.symbol ?? null,
    symbols: (p.symbols ?? []).join(', ') || null,
  })
}
