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
    localStorage.setItem(STORAGE_KEY, id)
    set({ themeId: id, theme: themes[id] })
  },

  initialize: () => {
    const saved = localStorage.getItem(STORAGE_KEY) as ThemeId | null
    if (saved && themes[saved]) {
      set({ themeId: saved, theme: themes[saved] })
    }
  },
}))
