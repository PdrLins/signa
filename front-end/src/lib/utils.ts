import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * Replace `{key}` placeholders in a template string with values from a vars object.
 */
export function interpolate(template: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (str, [key, val]) => str.replace(`{${key}}`, String(val)),
    template
  )
}

/**
 * Format a nullable number as `$X.XX`, returning `'--'` for null/undefined.
 */
export function formatPrice(v: number | null | undefined): string {
  if (v === null || v === undefined) return '--'
  return `$${Number(v).toFixed(2)}`
}

/** Mask IPv4 addresses — show only last octet, e.g. ***.***.***.123 */
export function maskIp(text: string): string {
  return text.replace(
    /\b(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b/g,
    (_match, _a, _b, _c, d) => `***.***.***.${d}`,
  )
}

/** Default timezone for date formatting (Toronto / US East). */
export const DEFAULT_TIMEZONE = 'America/New_York'

/** Check if NYSE/NASDAQ is open (Mon–Fri 9:30–16:00 ET). */
export function isMarketOpen(): boolean {
  const now = new Date()
  const et = new Date(now.toLocaleString('en-US', { timeZone: DEFAULT_TIMEZONE }))
  const day = et.getDay()
  if (day === 0 || day === 6) return false
  const minutes = et.getHours() * 60 + et.getMinutes()
  return minutes >= 570 && minutes < 960
}

/** Human-friendly relative timestamp, e.g. "2 min ago", "3h ago". */
export function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60_000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins} min ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}
