import { create } from 'zustand'
import { type Theme, type ThemeId, themes, DEFAULT_THEME } from '@/lib/themes'

const STORAGE_KEY = 'signa-theme'

interface ThemeStore {
  themeId: ThemeId
  theme: Theme
  setTheme: (id: ThemeId) => void
  initialize: () => void
}

export const useThemeStore = create<ThemeStore>((set) => ({
  themeId: DEFAULT_THEME,
  theme: themes[DEFAULT_THEME],

  setTheme: (id: ThemeId) => {
    try {
      localStorage.setItem(STORAGE_KEY, id)
    } catch (e) {
      console.warn('Failed to persist theme:', e)
    }
    set({ themeId: id, theme: themes[id] })
  },

  initialize: () => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY) as ThemeId | null
      if (saved && themes[saved]) {
        set({ themeId: saved, theme: themes[saved] })
      }
    } catch (e) {
      console.warn('Failed to read theme from localStorage:', e)
    }
  },
}))
