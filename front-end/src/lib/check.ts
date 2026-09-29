// Helpers for the "Check a stock" page. Pure (plus guarded localStorage).
import type { CheckResult, CheckText, CheckVerdict } from '@/types/check'
import { compactUsd, fill, nativePrice, shortDate } from '@/lib/insights'
import type en from '@/lib/i18n/en.json'

type T = typeof en

const PRICE_KEYS = new Set(['price', 'sma50', 'sma200'])

/** Render a back-end CheckText (hint / note / caveat) through t.check.<group>;
 *  unknown codes fall back to the back-end's English text. */
export function formatCheckText(
  item: CheckText,
  group: 'hints' | 'notes' | 'caveats',
  t: T,
  ctx: { symbol?: string | null; currency?: string | null; locale: string },
): string {
  const dict = t.check[group] as Record<string, string>
  let key = item.code
  if (group === 'notes' && key === 'ai_skipped' && item.params?.why === 'ai_disabled') key = 'ai_skipped_disabled'
  const tpl = dict[key]
  if (!tpl) return item.text
  const vars: Record<string, string | number | null> = {}
  for (const [k, v] of Object.entries(item.params ?? {})) {
    if (v === null || v === undefined || v === '') vars[k] = null
    else if (PRICE_KEYS.has(k)) vars[k] = nativePrice(Number(v), ctx.symbol, ctx.currency)
    else if (k === 'min' && key === 'liquidity') vars[k] = compactUsd(Number(v))
    else if (k === 'date') vars[k] = shortDate(String(v), ctx.locale, true)
    else if (k === 'corr') vars[k] = Number(v).toFixed(2)
    else vars[k] = v
  }
  // Drop "(~—)" left by a missing price.
  return fill(tpl, vars).replace(/\s*\(~—\)/g, '')
}

// ── Recent checks (per browser) ────────────────────────────────────

const RECENT_KEY = 'signa-recent-checks'
const RECENT_MAX = 8

export interface RecentCheck {
  symbol: string
  name: string | null
  verdict: CheckVerdict
  checked_at: string
}

function isRecent(x: unknown): x is RecentCheck {
  const r = x as RecentCheck
  return !!r && typeof r.symbol === 'string' && typeof r.verdict === 'string' && typeof r.checked_at === 'string'
}

export function loadRecent(): RecentCheck[] {
  try {
    const raw = window.localStorage.getItem(RECENT_KEY)
    const arr: unknown = raw ? JSON.parse(raw) : []
    return Array.isArray(arr) ? arr.filter(isRecent).slice(0, RECENT_MAX) : []
  } catch {
    return []
  }
}

export function saveRecent(r: CheckResult): RecentCheck[] {
  const entry: RecentCheck = { symbol: r.symbol, name: r.name, verdict: r.verdict, checked_at: r.checked_at }
  const next = [entry, ...loadRecent().filter((x) => x.symbol !== r.symbol)].slice(0, RECENT_MAX)
  try {
    window.localStorage.setItem(RECENT_KEY, JSON.stringify(next))
  } catch {
    // storage full / disabled — the list just won't persist
  }
  return next
}

export function clearRecent(): void {
  try {
    window.localStorage.removeItem(RECENT_KEY)
  } catch {
    // ignore
  }
}
