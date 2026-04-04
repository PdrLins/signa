import { useQuery } from '@tanstack/react-query'
import { signalsApi } from '@/lib/api'
import type { Signal, SignalFilters } from '@/types/signal'

export function useGemSignals() {
  return useQuery<Signal[]>({
    queryKey: ['signals', 'gems'],
    queryFn: async () => {
      const res = await signalsApi.getGems()
      return res.signals
    },
    staleTime: 5 * 60 * 1000,
    refetchInterval: 5 * 60 * 1000,
  })
}

export function useAllSignals(filters?: SignalFilters) {
  return useQuery<Signal[]>({
    queryKey: ['signals', filters],
    queryFn: async () => {
      const res = await signalsApi.getAll(filters)
      return res.signals
    },
  })
}

export function useSignalHistory(ticker: string) {
  return useQuery<Signal[]>({
    queryKey: ['signal', ticker],
    queryFn: async () => {
      const res = await signalsApi.getByTicker(ticker)
      return res.signals
    },
    enabled: !!ticker,
  })
}
