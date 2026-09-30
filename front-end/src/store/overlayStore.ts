import { create } from 'zustand'
import type { LimitCode } from '@/lib/access'

/** App-wide overlays: the global stock search (⌘K / Ctrl+K, header search
 *  buttons) and the upgrade sheet opened by a 403 slot_limit / alert_limit. */
interface OverlayStore {
  searchOpen: boolean
  openSearch: () => void
  closeSearch: () => void
  /** null = closed */
  upgrade: { reason: LimitCode; limit: number | null } | null
  openUpgrade: (reason: LimitCode, limit?: number | null) => void
  closeUpgrade: () => void
}

export const useOverlayStore = create<OverlayStore>((set) => ({
  searchOpen: false,
  openSearch: () => set({ searchOpen: true }),
  closeSearch: () => set({ searchOpen: false }),
  upgrade: null,
  openUpgrade: (reason, limit = null) => set({ upgrade: { reason, limit: limit ?? null } }),
  closeUpgrade: () => set({ upgrade: null }),
}))
