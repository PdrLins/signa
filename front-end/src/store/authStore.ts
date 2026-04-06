import { create } from 'zustand'
import { TOKEN_KEY } from '@/lib/constants'

function setCookie(token: string) {
  try {
    document.cookie = `${TOKEN_KEY}=${token}; path=/; SameSite=Strict; max-age=86400`
  } catch {
    // SSR or cookie access denied — ignore
  }
}

function clearCookie() {
  try {
    document.cookie = `${TOKEN_KEY}=; path=/; max-age=0`
  } catch {
    // SSR or cookie access denied — ignore
  }
}

interface AuthStore {
  token: string | null
  isAuthenticated: boolean
  setToken: (token: string) => void
  logout: () => void
  initialize: () => void
}

export const useAuthStore = create<AuthStore>((set) => ({
  token: null,
  isAuthenticated: false,

  setToken: (token: string) => {
    try {
      localStorage.setItem(TOKEN_KEY, token)
    } catch {
      // localStorage unavailable — continue with in-memory token
    }
    setCookie(token)
    set({ token, isAuthenticated: true })
  },

  logout: () => {
    try {
      localStorage.removeItem(TOKEN_KEY)
    } catch {
      // localStorage unavailable — ignore
    }
    clearCookie()
    set({ token: null, isAuthenticated: false })
  },

  initialize: () => {
    try {
      const token = localStorage.getItem(TOKEN_KEY)
      if (token) {
        setCookie(token)
        set({ token, isAuthenticated: true })
      }
    } catch {
      // localStorage unavailable — remain unauthenticated
    }
  },
}))
