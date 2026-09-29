import { useQuery } from '@tanstack/react-query'
import { insightsApi } from '@/lib/api'
import type { TodayInsights, PerformanceInsights, BacktestInsights, SignalTrail, SignalVerdict } from '@/types/insights'

export function useTodayInsights() {
  return useQuery<TodayInsights>({
    queryKey: ['insights', 'today'],
    queryFn: () => insightsApi.getToday(),
    staleTime: 30_000,
    refetchInterval: 60_000,
  })
}

export function usePerformanceInsights() {
  return useQuery<PerformanceInsights>({
    queryKey: ['insights', 'performance'],
    queryFn: () => insightsApi.getPerformance(),
    staleTime: 5 * 60_000,
  })
}

export function useBacktestInsights() {
  return useQuery<BacktestInsights>({
    queryKey: ['insights', 'backtest'],
    queryFn: () => insightsApi.getBacktest(),
    staleTime: 30 * 60_000,
  })
}

export function useSignalTrail(ticker: string) {
  return useQuery<SignalTrail>({
    queryKey: ['insights', 'signal', ticker],
    queryFn: () => insightsApi.getSignalTrail(ticker),
    enabled: !!ticker,
    staleTime: 60_000,
    retry: (count, err) => count < 1 && !/not found|404/i.test(String((err as Error)?.message)),
  })
}

/** AI verdict chips for a list of signal ids (max 200). */
export function useSignalVerdicts(ids: string[]) {
  const key = ids.slice(0, 200).sort().join(',')
  return useQuery<Record<string, SignalVerdict>>({
    queryKey: ['insights', 'verdicts', key],
    queryFn: async () => (await insightsApi.getVerdicts(key.split(','))).verdicts,
    enabled: key.length > 0,
    staleTime: 2 * 60_000,
  })
}
