import { useQuery } from '@tanstack/react-query'
import { stocksApi, CheckApiError } from '@/lib/api'
import type { StockPage } from '@/types/stock'

export const stockKey = (symbol: string) => ['stock', symbol.toUpperCase()] as const

/** Free stock page data (GET /stocks/{symbol}). The server caches the
 *  shared part ~15 min, so a 5-minute client stale time is plenty. */
export function useStock(symbol: string) {
  return useQuery<StockPage, Error>({
    queryKey: stockKey(symbol),
    queryFn: () => stocksApi.get(symbol),
    enabled: !!symbol,
    staleTime: 5 * 60 * 1000,
    // an unknown / invalid symbol won't appear on retry
    retry: (count, err) => !(err instanceof CheckApiError && (err.status === 404 || err.status === 400)) && count < 1,
  })
}
