// Formatting helpers for the insights pages (Today, Is it working?,
// signal decision trail). Pure functions — no React.
import type { ReasonInfo } from '@/types/insights'
import { DEFAULT_TIMEZONE } from '@/lib/utils'
import type en from '@/lib/i18n/en.json'

type T = typeof en

export const DASH = '—'

/** Replace every `{key}` in `template`; null/undefined values become "—". */
export function fill(template: string, vars: Record<string, string | number | null | undefined>): string {
  return template.replace(/\{(\w+)\}/g, (m, k: string) => {
    if (!(k in vars)) return m
    const v = vars[k]
    return v === null || v === undefined || v === '' ? DASH : String(v)
  })
}

/** Signed percent from a PERCENT number: 1.234 -> "+1.23%". */
export function signedPct(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return DASH
  const r = Number(v.toFixed(digits))
  if (r === 0) return `${(0).toFixed(digits)}%`
  return `${r > 0 ? '+' : '−'}${Math.abs(r).toFixed(digits)}%`
}

/** Signed percent from a DECIMAL fraction: 0.0123 -> "+1.23%". */
export function signedFracPct(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return DASH
  return signedPct(v * 100, digits)
}

export function money(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return DASH
  return `$${v.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })}`
}

/** Native-currency price: CAD for .TO, USD otherwise. */
export function nativePrice(v: number | null | undefined, symbol?: string | null, currency?: string | null): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return DASH
  const cad = currency === 'CAD' || (symbol ?? '').toUpperCase().endsWith('.TO')
  const digits = v >= 1000 ? 0 : v >= 1 ? 2 : 4
  return `${cad ? 'C$' : '$'}${v.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })}`
}

export function num(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return DASH
  return v.toFixed(digits)
}

/** Compact dollar volume: 32_000_000_000 -> "$32B". */
export function compactUsd(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return DASH
  const abs = Math.abs(v)
  if (abs >= 1e9) return `$${(v / 1e9).toFixed(abs >= 1e10 ? 0 : 1)}B`
  if (abs >= 1e6) return `$${(v / 1e6).toFixed(abs >= 1e7 ? 0 : 1)}M`
  if (abs >= 1e3) return `$${(v / 1e3).toFixed(0)}K`
  return `$${v.toFixed(0)}`
}

export function etTime(iso: string | null | undefined, locale: string): string {
  if (!iso) return DASH
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return DASH
  return d.toLocaleTimeString(locale === 'pt' ? 'pt-BR' : 'en-US', {
    hour: 'numeric', minute: '2-digit', timeZone: DEFAULT_TIMEZONE, timeZoneName: 'short',
  })
}

export function shortDate(iso: string | null | undefined, locale: string, withYear = false): string {
  if (!iso) return DASH
  // date-only strings are calendar dates, not instants: don't shift them
  const d = /^\d{4}-\d{2}-\d{2}$/.test(iso) ? new Date(`${iso}T12:00:00Z`) : new Date(iso)
  if (Number.isNaN(d.getTime())) return DASH
  return d.toLocaleDateString(locale === 'pt' ? 'pt-BR' : 'en-US', {
    month: 'short', day: 'numeric', ...(withYear ? { year: 'numeric' } : {}), timeZone: DEFAULT_TIMEZONE,
  })
}

function humanize(raw: string): string {
  const s = raw.replace(/^short:/, 'short: ').replace(/[_:]+/g, ' ').trim()
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : raw
}

/**
 * Render a back-end ReasonInfo through the i18n dictionary. Unknown codes
 * fall back to the back-end's English text, then to the humanized raw code.
 */
export function formatReason(reason: ReasonInfo | null | undefined, t: T): string {
  if (!reason) return DASH
  const r = t.reasons as unknown as Record<string, string | Record<string, string>>
  const p = reason.params || {}
  const tpl = (k: string) => (typeof r[k] === 'string' ? (r[k] as string) : null)
  const hasAll = (...keys: string[]) => keys.every((k) => p[k] !== null && p[k] !== undefined && p[k] !== '')

  switch (reason.code) {
    case 'entered':
      return hasAll('size_usd')
        ? fill(t.reasons.entered, { size: money(Number(p.size_usd), 0), risk: p.risk_pct != null ? Number(p.risk_pct).toFixed(1) : null })
        : t.reasons.enteredShort
    case 'correlation_limit':
      if (p.rule === 'correlated_cluster' && hasAll('cluster'))
        return fill(t.reasons.correlation_cluster, { threshold: p.threshold != null ? Number(p.threshold).toFixed(2) : null, cluster: p.cluster })
      return fill(t.reasons.correlation_limit, {
        corr: p.corr != null ? Number(p.corr).toFixed(2) : null,
        symbol: p.symbol, limit: p.limit != null ? Number(p.limit).toFixed(2) : null,
      })
    case 'earnings_blackout':
      return hasAll('days') ? fill(t.reasons.earnings_blackout, { days: p.days, limit: p.limit }) : t.reasons.earnings_blackout_short
    case 'drawdown_breaker_pause':
      return hasAll('days_remaining') ? fill(t.reasons.drawdown_breaker_pause, { days: p.days_remaining }) : t.reasons.drawdown_breaker_pause_short
    case 'technical_filter': {
      const check = String(p.check ?? '')
      const checks = t.reasons.checks as Record<string, string>
      let text: string
      if ((check === 'overextended_vs_sma50' || check === 'rsi_overbought') && !hasAll('value')) {
        text = checks[`${check}_short`] ?? humanize(check)
      } else if (checks[check]) {
        text = fill(checks[check], {
          value: p.value != null ? Number(p.value).toFixed(check === 'rsi_overbought' ? 0 : 1) : null,
          limit: p.limit,
        })
      } else {
        text = humanize(check || 'filter')
      }
      return fill(t.reasons.technical_filter, { check: text })
    }
    case 'rr_below_min':
      return fill(t.reasons.rr_below_min, {
        rr: p.rr != null ? Number(p.rr).toFixed(2) : null, min: p.min != null ? Number(p.min).toFixed(1) : null,
      })
    case 'portfolio_beta_limit':
      return fill(t.reasons.portfolio_beta_limit, {
        beta: p.beta != null ? Number(p.beta).toFixed(2) : null, limit: p.limit,
      })
    case 'decision_veto':
      return fill(t.reasons.decision_veto, { signal: p.decision_signal ?? p.signal })
    case 'reentry_cooldown':
      return fill(t.reasons.reentry_cooldown, { days: p.days != null ? `${p.days}d` : null })
    case 'other':
      return reason.text || humanize(String(p.raw ?? reason.raw ?? ''))
    default: {
      const tp = tpl(reason.code)
      if (tp) return fill(tp, p)
      return reason.text || humanize(reason.raw ?? reason.code)
    }
  }
}

/** Human label for a normalized skip gate from candidate_outcomes (e.g.
 *  'rr_below_min', 'technical_filter:overextended_vs_sma50',
 *  'not_ai_buy_rejected_HOLD'). */
export function gateLabel(gate: string, t: T): string {
  const gates = t.reasons.gates as Record<string, string>
  if (gate.startsWith('technical_filter:')) {
    const rest = gate.slice('technical_filter:'.length)
    const checks = t.reasons.checks as Record<string, string>
    const short = checks[`${rest}_short`] ?? (checks[rest] && !checks[rest].includes('{') ? checks[rest] : humanize(rest))
    return fill(t.reasons.technical_filter, { check: short })
  }
  if (gates[gate]) return gates[gate]
  const m = /^not_ai_buy_(rejected|skipped|low_confidence|failed)_?(.*)$/.exec(gate)
  if (m) {
    if (m[1] === 'rejected') return fill(gates.ai_rejected, { signal: m[2] || null })
    if (m[1] === 'skipped') return gates.ai_not_called
    if (m[1] === 'low_confidence') return gates.ai_low_confidence
    return gates.ai_failed
  }
  const base = Object.keys(gates).find((k) => gate.startsWith(k))
  return base ? gates[base] : humanize(gate)
}
