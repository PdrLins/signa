import { create } from 'zustand'
import type { AccessLevel } from '@/types/access'

const KEY = 'signa-view-as'

function read(): AccessLevel | null {
  try {
    const v = localStorage.getItem(KEY)
    return v === 'free' || v === 'premium' || v === 'owner' ? v : null
  } catch {
    return null
  }
}

/** Dev tools: preview the app as another access level. Sent to the API as
 *  the X-View-As header; the back-end honours it only for owners when
 *  DEV_TOOLS_ENABLED is on, so it can never raise anyone's access. */
interface ViewAsStore {
  viewAs: AccessLevel | null
  setViewAs: (level: AccessLevel | null) => void
}

export const useViewAsStore = create<ViewAsStore>((set) => ({
  viewAs: typeof window !== 'undefined' ? read() : null,
  setViewAs: (level) => {
    try {
      if (level) localStorage.setItem(KEY, level)
      else localStorage.removeItem(KEY)
    } catch {
      // storage unavailable: keep it in memory only
    }
    set({ viewAs: level })
  },
}))
