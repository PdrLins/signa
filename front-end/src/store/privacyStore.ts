import { create } from 'zustand'

const KEY = 'signa-hide-amounts'

interface PrivacyStore {
  /** Mask money values on /home, /holdings and /dividends (per device). */
  hidden: boolean
  loaded: boolean
  load: () => void
  toggle: () => void
}

export const usePrivacyStore = create<PrivacyStore>((set, get) => ({
  hidden: false,
  loaded: false,
  load: () => {
    if (get().loaded) return
    let hidden = false
    try {
      hidden = window.localStorage.getItem(KEY) === '1'
    } catch {
      // storage blocked — default to visible
    }
    set({ hidden, loaded: true })
  },
  toggle: () => {
    const hidden = !get().hidden
    try {
      window.localStorage.setItem(KEY, hidden ? '1' : '0')
    } catch {
      // storage blocked — keep the in-memory choice
    }
    set({ hidden, loaded: true })
  },
}))
