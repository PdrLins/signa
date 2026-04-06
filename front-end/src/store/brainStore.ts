import { create } from 'zustand'

interface BrainStore {
  brainToken: string | null
  brainTokenExpiry: Date | null
  isUnlocked: boolean

  setBrainToken: (token: string, expiresIn: number) => void
  lock: () => void
  getRemainingSeconds: () => number
  getHeaders: () => Record<string, string>
}

let _timer: ReturnType<typeof setTimeout> | null = null

export const useBrainStore = create<BrainStore>((set, get) => ({
  brainToken: null,
  brainTokenExpiry: null,
  isUnlocked: false,

  setBrainToken: (token: string, expiresIn: number) => {
    const expiry = new Date(Date.now() + expiresIn * 1000)
    set({ brainToken: token, brainTokenExpiry: expiry, isUnlocked: true })

    // Clear any existing timer
    if (_timer) clearTimeout(_timer)

    // Lock exactly when token expires — no polling
    _timer = setTimeout(() => get().lock(), expiresIn * 1000)
  },

  lock: () => {
    if (_timer) {
      clearTimeout(_timer)
      _timer = null
    }
    set({ brainToken: null, brainTokenExpiry: null, isUnlocked: false })
  },

  getRemainingSeconds: () => {
    const { brainTokenExpiry } = get()
    if (!brainTokenExpiry) return 0
    return Math.max(0, Math.floor((brainTokenExpiry.getTime() - Date.now()) / 1000))
  },

  getHeaders: () => {
    const { brainToken } = get()
    const headers: Record<string, string> = {}
    if (brainToken) headers['X-Brain-Token'] = brainToken
    return headers
  },
}))
