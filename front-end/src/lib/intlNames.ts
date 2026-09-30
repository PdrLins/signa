// Country / currency names in the user's language via Intl (no hardcoded lists).
import { INTL_LOCALES, type Locale } from '@/store/i18nStore'

const cache = new Map<string, Intl.DisplayNames | null>()

function names(locale: string, type: 'region' | 'currency'): Intl.DisplayNames | null {
  const key = `${locale}:${type}`
  if (!cache.has(key)) {
    try {
      cache.set(key, new Intl.DisplayNames([INTL_LOCALES[locale as Locale] ?? 'en-CA'], { type }))
    } catch {
      cache.set(key, null)
    }
  }
  return cache.get(key) ?? null
}

export function countryName(code: string, locale: string): string {
  try {
    return names(locale, 'region')?.of(code) ?? code
  } catch {
    return code
  }
}

export function currencyName(code: string, locale: string): string {
  try {
    const n = names(locale, 'currency')?.of(code)
    return n && n !== code ? `${code} — ${n}` : code
  } catch {
    return code
  }
}
