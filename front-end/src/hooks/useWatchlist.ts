import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { watchlistApi } from '@/lib/api'
import type { WatchlistItem } from '@/types/watchlist'

export function useWatchlist() {
  return useQuery<WatchlistItem[]>({
    queryKey: ['watchlist'],
    queryFn: async () => {
      const res = await watchlistApi.getAll()
      return res.items
    },
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
    },
  })
}
