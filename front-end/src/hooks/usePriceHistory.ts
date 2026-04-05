import { useQuery } from '@tanstack/react-query'
import { client } from '@/lib/api'
import type { PricePoint, TimeRange } from '@/types/chart'

const RANGE_TO_PERIOD: Record<TimeRange, string> = {
  '1D': '1d',
  '1W': '5d',
  '1M': '1mo',
  '3M': '3mo',
}

export function usePriceHistory(symbol: string, range: TimeRange = '1M') {
  return useQuery<PricePoint[]>({
    queryKey: ['price-history', symbol, range],
    queryFn: async () => {
      const period = RANGE_TO_PERIOD[range]
      const res = await client.get(`/tickers/${symbol}/chart`, { params: { period } })
      const data = res.data as { data_points?: Array<{ date: string; close: number }> }

      if (data.data_points && data.data_points.length > 0) {
        return data.data_points.map((p) => ({
          date: p.date,
          price: p.close,
        }))
      }

      return []
    },
    staleTime: 5 * 60 * 1000,
    enabled: !!symbol,
    retry: 1,
  })
}
