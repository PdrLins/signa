import { create } from 'zustand'
import { type Theme, type ThemeId, themes, DEFAULT_THEME } from '@/lib/themes'

const STORAGE_KEY = 'signa-theme'

interface ThemeStore {
  themeId: ThemeId
  theme: Theme
  setTheme: (id: ThemeId) => void
  initialize: () => void
  loadFromServer: () => void
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
    // Sync to server
    import('@/lib/api').then(({ client }) => {
      client.put('/stats/user-settings', { theme: id }).catch(() => {})
    }).catch(() => {})
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

  loadFromServer: () => {
    import('@/lib/api').then(({ client }) => {
      client.get('/stats/user-settings').then((res) => {
        const data = res.data as { theme?: string; language?: string }
        if (data.theme && themes[data.theme as ThemeId]) {
          const id = data.theme as ThemeId
          localStorage.setItem(STORAGE_KEY, id)
          set({ themeId: id, theme: themes[id] })
        }
      }).catch(() => {})
    }).catch(() => {})
  },
}))
