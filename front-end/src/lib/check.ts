// Helpers for the "Check a stock" page. Pure (plus guarded localStorage).
import type { AnyCheckResult, CheckMode, CheckText, CheckVerdict, LongVerdict } from '@/types/check'
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
  verdict: CheckVerdict | LongVerdict
  checked_at: string
  /** entries saved before long-term mode existed have no mode -> short */
  mode: CheckMode
}

function isRecent(x: unknown): x is RecentCheck {
  const r = x as RecentCheck
  return !!r && typeof r.symbol === 'string' && typeof r.verdict === 'string' && typeof r.checked_at === 'string'
}

export function loadRecent(): RecentCheck[] {
  try {
    const raw = window.localStorage.getItem(RECENT_KEY)
    const arr: unknown = raw ? JSON.parse(raw) : []
    return Array.isArray(arr)
      ? arr.filter(isRecent).slice(0, RECENT_MAX).map((r) => ({ ...r, mode: r.mode === 'long' ? 'long' : 'short' }))
      : []
  } catch {
    return []
  }
}

export function saveRecent(r: AnyCheckResult): RecentCheck[] {
  const mode: CheckMode = r.mode === 'long' ? 'long' : 'short'
  const entry: RecentCheck = { symbol: r.symbol, name: r.name, verdict: r.verdict, checked_at: r.checked_at, mode }
  const next = [entry, ...loadRecent().filter((x) => !(x.symbol === r.symbol && x.mode === mode))].slice(0, RECENT_MAX)
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

// ── Preferred mode (per browser) ───────────────────────────────────

const MODE_KEY = 'signa-check-mode'

export function parseMode(v: string | null | undefined): CheckMode | null {
  return v === 'long' || v === 'short' ? v : null
}

export function loadMode(): CheckMode {
  try {
    return parseMode(window.localStorage.getItem(MODE_KEY)) ?? 'short'
  } catch {
    return 'short'
  }
}

export function saveMode(mode: CheckMode): void {
  try {
    window.localStorage.setItem(MODE_KEY, mode)
  } catch {
    // storage disabled — the choice just won't persist
  }
}

/** /check URL for a ticker + mode (short is the default and omitted). */
export function checkHref(ticker: string, mode: CheckMode): string {
  const q = `ticker=${encodeURIComponent(ticker)}`
  return mode === 'long' ? `/check?${q}&mode=long` : `/check?${q}`
}

// ── Compare (2–3 symbols) ──────────────────────────────────────────

export const COMPARE_MIN = 2
export const COMPARE_MAX = 3
const COMPARE_KEY = 'signa-compare-set'

/** "aapl, msft,,NVDA" -> ["AAPL","MSFT","NVDA"] (max 3, deduped). */
export function parseCompareParam(v: string | null | undefined): string[] {
  if (!v) return []
  const out: string[] = []
  for (const part of v.split(',')) {
    const s = part.trim().toUpperCase()
    if (s && !out.includes(s) && out.length < COMPARE_MAX) out.push(s)
  }
  return out
}

/** /check URL for a comparison (short is the default and omitted). */
export function compareHref(tickers: string[], mode: CheckMode): string {
  const q = `compare=${tickers.map(encodeURIComponent).join(',')}`
  return mode === 'long' ? `/check?${q}&mode=long` : `/check?${q}`
}

export function loadCompareSet(): { tickers: string[]; mode: CheckMode } | null {
  try {
    const raw = window.localStorage.getItem(COMPARE_KEY)
    const v = raw ? (JSON.parse(raw) as { tickers?: unknown; mode?: unknown }) : null
    if (!v || !Array.isArray(v.tickers)) return null
    const tickers = parseCompareParam(v.tickers.filter((x) => typeof x === 'string').join(','))
    return tickers.length ? { tickers, mode: parseMode(v.mode as string) ?? 'short' } : null
  } catch {
    return null
  }
}

export function saveCompareSet(tickers: string[], mode: CheckMode): void {
  try {
    window.localStorage.setItem(COMPARE_KEY, JSON.stringify({ tickers, mode }))
  } catch {
    // storage disabled — the set just won't persist
  }
}
