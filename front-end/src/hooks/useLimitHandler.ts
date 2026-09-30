import { useCallback } from 'react'
import { isLimitError } from '@/lib/access'
import { useOverlayStore } from '@/store/overlayStore'

/** Turns a 403 slot_limit / alert_limit into the upgrade sheet (not a toast).
 *  Returns true when it handled the error, so callers show their own
 *  message only for other errors:
 *    onError: (e) => { if (!handleLimit(e)) toast.show(...) } */
export function useLimitHandler() {
  const openUpgrade = useOverlayStore((s) => s.openUpgrade)
  return useCallback((e: unknown): boolean => {
    if (!isLimitError(e)) return false
    openUpgrade(e.code, e.limit ?? null)
    return true
  }, [openUpgrade])
}
