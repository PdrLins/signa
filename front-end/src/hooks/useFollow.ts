import { useCallback } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useAddTicker, useRemoveTicker } from '@/hooks/useWatchlist'
import { useLimitHandler } from '@/hooks/useLimitHandler'
import { useToast } from '@/hooks/useToast'
import { useI18nStore } from '@/store/i18nStore'
import { fill } from '@/lib/insights'

/** One-tap follow / unfollow (the watchlist) used by the stock page and the
 *  global search. A 403 slot_limit opens the upgrade sheet instead of a
 *  toast; the stock page, watchlist and slot count are refreshed. */
export function useFollow() {
  const t = useI18nStore((s) => s.t)
  const toast = useToast()
  const qc = useQueryClient()
  const handleLimit = useLimitHandler()
  const add = useAddTicker()
  const remove = useRemoveTicker()

  const refresh = useCallback((symbol: string) => {
    qc.invalidateQueries({ queryKey: ['stock', symbol.toUpperCase()] })
  }, [qc])

  const follow = useCallback((symbol: string) => {
    add.mutate(symbol, {
      onSuccess: () => { toast.show(fill(t.search.followed, { symbol }), 'success'); refresh(symbol) },
      onError: (e) => { if (!handleLimit(e)) toast.show(t.search.failed, 'error') },
    })
  }, [add, toast, t, refresh, handleLimit])

  const unfollow = useCallback((symbol: string) => {
    remove.mutate(symbol, {
      onSuccess: () => { toast.show(fill(t.search.unfollowed, { symbol }), 'info'); refresh(symbol) },
      onError: () => toast.show(t.search.failed, 'error'),
    })
  }, [remove, toast, t, refresh])

  return { follow, unfollow, busy: add.isPending || remove.isPending, pendingSymbol: add.variables ?? remove.variables }
}
