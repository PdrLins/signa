'use client'

import { useTheme } from '@/hooks/useTheme'
import { useI18nStore, type Locale } from '@/store/i18nStore'

const OPTIONS: { code: Locale; short: string; label: string }[] = [
  { code: 'en', short: 'EN', label: 'English (Canada)' },
  { code: 'pt', short: 'PT', label: 'Português (Brasil)' },
]

/**
 * Language switch: English (Canada) / Português (Brasil).
 * - variant "rail": one compact button for the floating left rail; each
 *   click flips to the other language.
 * - variant "segmented" (default): both options side by side, for the
 *   mobile More sheet and the login page.
 */
export function LangSwitcher({ variant = 'segmented' }: { variant?: 'rail' | 'segmented' }) {
  const theme = useTheme()
  const locale = useI18nStore((s) => s.locale)
  const setLocale = useI18nStore((s) => s.setLocale)

  if (variant === 'rail') {
    const next = OPTIONS.find((o) => o.code !== locale) ?? OPTIONS[0]
    const current = OPTIONS.find((o) => o.code === locale) ?? OPTIONS[0]
    return (
      <button
        type="button"
        onClick={() => setLocale(next.code)}
        className="flex items-center justify-center w-10 h-10 rounded-xl text-[11px] font-bold tracking-wide transition-all hover:opacity-80 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        style={{ color: theme.colors.textSub, outlineColor: theme.colors.primary, border: `1px solid ${theme.colors.border}` }}
        title={`${current.label} → ${next.label}`}
        aria-label={`${current.label}. Switch to ${next.label}`}
      >
        {current.short}
      </button>
    )
  }

  return (
    <div
      role="radiogroup"
      aria-label="Language / Idioma"
      className="inline-flex rounded-xl p-1 gap-1"
      style={{ backgroundColor: theme.colors.surfaceAlt, border: `1px solid ${theme.colors.border}` }}
    >
      {OPTIONS.map((o) => {
        const active = o.code === locale
        return (
          <button
            key={o.code}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => setLocale(o.code)}
            aria-label={o.label}
            title={o.label}
            className="min-h-[44px] min-w-[44px] px-3 rounded-lg text-[13px] font-semibold tracking-wide transition-all focus-visible:outline focus-visible:outline-2"
            style={{
              backgroundColor: active ? theme.colors.primary + '1f' : 'transparent',
              color: active ? theme.colors.primary : theme.colors.textSub,
              outlineColor: theme.colors.primary,
            }}
          >
            {o.short}
          </button>
        )
      })}
    </div>
  )
}
