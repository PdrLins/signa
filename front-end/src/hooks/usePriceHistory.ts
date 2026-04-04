import { useQuery } from '@tanstack/react-query'
import type { PricePoint, TimeRange } from '@/types/chart'

function generateMockData(range: TimeRange, basePrice: number): PricePoint[] {
  const points: PricePoint[] = []
  const now = new Date()
  let count: number
  let stepMs: number

  switch (range) {
    case '1D':
      count = 78 // 6.5 hours of trading, 5-min intervals
      stepMs = 5 * 60 * 1000
      break
    case '1W':
      count = 35 // 5 days, ~7 points per day
      stepMs = 60 * 60 * 1000
      break
    case '1M':
      count = 22 // trading days in a month
      stepMs = 24 * 60 * 60 * 1000
      break
    case '3M':
      count = 65
      stepMs = 24 * 60 * 60 * 1000
      break
  }

  let price = basePrice
  for (let i = count; i >= 0; i--) {
    const date = new Date(now.getTime() - i * stepMs)
    const change = (Math.random() - 0.48) * basePrice * 0.015
    price = Math.max(price + change, basePrice * 0.8)
    points.push({
      date: date.toISOString(),
      price: Math.round(price * 100) / 100,
    })
  }

  return points
}

export function usePriceHistory(symbol: string, range: TimeRange = '1M', basePrice?: number) {
  return useQuery<PricePoint[]>({
    queryKey: ['price-history', symbol, range],
    queryFn: async () => {
      // TODO: Replace with real API call when backend supports price history
      // e.g. const res = await api.get(`/prices/${symbol}?range=${range}`)
      return generateMockData(range, basePrice ?? 100)
    },
    staleTime: 5 * 60 * 1000,
    enabled: !!symbol,
  })
}
