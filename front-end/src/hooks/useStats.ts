import { useQuery } from '@tanstack/react-query'
import { statsApi } from '@/lib/api'
import type { DailyStats } from '@/types/signal'

export function useStats() {
  return useQuery<DailyStats>({
    queryKey: ['stats', 'daily'],
    queryFn: () => statsApi.getDaily(),
    staleTime: 60 * 1000,
    refetchInterval: 60 * 1000,
  })
}
