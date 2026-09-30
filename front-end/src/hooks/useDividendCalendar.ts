'use client'

import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { dividendsApi, CheckApiError } from '@/lib/api'
import type { DividendCalendarResponse } from '@/types/dividends'

export const DIVIDEND_CALENDAR_KEY = ['dividends', 'calendar'] as const

/** GET /dividends/calendar — shared market data cached ~12h server-side. */
export function useDividendCalendar(months = 12, includeWatchlist = false) {
  return useQuery<DividendCalendarResponse, unknown>({
    queryKey: [...DIVIDEND_CALENDAR_KEY, months, includeWatchlist],
    queryFn: () => dividendsApi.calendar(months, includeWatchlist),
    staleTime: 10 * 60_000,
    placeholderData: keepPreviousData,
    retry: (count, err) => !(err instanceof CheckApiError && err.status === 503) && count < 2,
  })
}
