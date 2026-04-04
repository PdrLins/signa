import { create } from 'zustand'

const TOKEN_KEY = 'signa-token'

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
    localStorage.setItem(TOKEN_KEY, token)
    set({ token, isAuthenticated: true })
  },

  logout: () => {
    localStorage.removeItem(TOKEN_KEY)
    set({ token: null, isAuthenticated: false })
  },

  initialize: () => {
    const token = localStorage.getItem(TOKEN_KEY)
    if (token) {
      set({ token, isAuthenticated: true })
    }
  },
}))
