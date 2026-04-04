'use client'

import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'

export function LangSwitcher() {
  const theme = useTheme()
  const locale = useI18nStore((s) => s.locale)
  const setLocale = useI18nStore((s) => s.setLocale)

  return (
    <button
      onClick={() => setLocale(locale === 'en' ? 'pt' : 'en')}
      className="px-2 py-1 rounded-lg text-[11px] font-semibold transition-all"
      style={{
        backgroundColor: theme.colors.surfaceAlt,
        color: theme.colors.textSub,
        border: `0.5px solid ${theme.colors.border}`,
      }}
      title={locale === 'en' ? 'Mudar para Portugues' : 'Switch to English'}
    >
      {locale === 'en' ? 'PT' : 'EN'}
    </button>
  )
}
