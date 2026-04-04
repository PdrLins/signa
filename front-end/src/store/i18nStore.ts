import { create } from 'zustand'
import en from '@/lib/i18n/en.json'
import pt from '@/lib/i18n/pt.json'

const LANG_KEY = 'signa-lang'

type Locale = 'en' | 'pt'
type Translations = typeof en

const locales: Record<Locale, Translations> = { en, pt }

interface I18nStore {
  locale: Locale
  t: Translations
  setLocale: (locale: Locale) => void
  initialize: () => void
}

export const useI18nStore = create<I18nStore>((set) => ({
  locale: 'en',
  t: en,

  setLocale: (locale: Locale) => {
    localStorage.setItem(LANG_KEY, locale)
    set({ locale, t: locales[locale] })
  },

  initialize: () => {
    const saved = localStorage.getItem(LANG_KEY) as Locale | null
    if (saved && locales[saved]) {
      set({ locale: saved, t: locales[saved] })
    }
  },
}))
