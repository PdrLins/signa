import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { watchlistApi } from '@/lib/api'
import type { FollowingOverview, WatchlistItem } from '@/types/watchlist'

export function useWatchlist() {
  return useQuery<WatchlistItem[]>({
    queryKey: ['watchlist'],
    queryFn: async () => {
      const res = await watchlistApi.getAll()
      return res.items
    },
  })
}

export const FOLLOWING_KEY = ['following'] as const

/** The Following tab: watched + held symbols with prices and sparklines.
 *  Prices are shared server-side quotes (delayed), so a 60s poll is cheap. */
export function useFollowing(enabled = true) {
  return useQuery<FollowingOverview>({
    queryKey: FOLLOWING_KEY,
    queryFn: () => watchlistApi.overview(),
    enabled,
    refetchInterval: 60_000,
    staleTime: 30_000,
  })
}

export function useAddTicker() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (ticker: string) => watchlistApi.add(ticker),
    onMutate: async (ticker) => {
      await queryClient.cancelQueries({ queryKey: ['watchlist'] })
      const previous = queryClient.getQueryData<WatchlistItem[]>(['watchlist'])
      queryClient.setQueryData<WatchlistItem[]>(['watchlist'], (old = []) => [
        ...old,
        {
          id: `temp-${ticker}`,
          symbol: ticker.toUpperCase(),
          added_at: new Date().toISOString(),
          notes: null,
        },
      ])
      return { previous }
    },
    onError: (_err, _ticker, context) => {
      if (context?.previous) {
        queryClient.setQueryData(['watchlist'], context.previous)
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['watchlist'] })
      queryClient.invalidateQueries({ queryKey: ['auth', 'me'] }) // slot count
      queryClient.invalidateQueries({ queryKey: FOLLOWING_KEY })
    },
  })
}

export function useRemoveTicker() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (ticker: string) => watchlistApi.remove(ticker),
    onMutate: async (ticker) => {
      await queryClient.cancelQueries({ queryKey: ['watchlist'] })
      const previous = queryClient.getQueryData<WatchlistItem[]>(['watchlist'])
      queryClient.setQueryData<WatchlistItem[]>(['watchlist'], (old = []) =>
        old.filter((item) => item.symbol !== ticker)
      )
      return { previous }
    },
    onError: (_err, _ticker, context) => {
      if (context?.previous) {
        queryClient.setQueryData(['watchlist'], context.previous)
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['watchlist'] })
      queryClient.invalidateQueries({ queryKey: ['auth', 'me'] }) // slot count
      queryClient.invalidateQueries({ queryKey: FOLLOWING_KEY })
    },
  })
}
