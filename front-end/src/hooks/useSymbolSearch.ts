import { useEffect, useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { symbolsApi } from '@/lib/api'
import type { SymbolMatch } from '@/types/symbols'

export const SYMBOL_SEARCH_DEBOUNCE_MS = 250
const EMPTY: SymbolMatch[] = []

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setV(value), ms)
    return () => clearTimeout(id)
  }, [value, ms])
  return v
}

/** Suggestions for a ticker / company-name query (debounced ~250ms).
 *  `pending` is true while the typed text hasn't been searched yet. */
export function useSymbolSearch(q: string, { enabled = true, limit = 8 }: { enabled?: boolean; limit?: number } = {}) {
  const trimmed = q.trim().replace(/\s+/g, ' ').slice(0, 40)
  const debounced = useDebounced(trimmed, SYMBOL_SEARCH_DEBOUNCE_MS)
  const on = enabled && debounced.length >= 1
  const query = useQuery<SymbolMatch[]>({
    queryKey: ['symbol-search', debounced.toLowerCase(), limit],
    queryFn: async ({ signal }) => (await symbolsApi.search(debounced, limit, signal)).results,
    enabled: on,
    placeholderData: keepPreviousData,
    staleTime: 10 * 60_000,
    gcTime: 30 * 60_000,
    retry: false,
  })
  return {
    results: on ? query.data ?? EMPTY : EMPTY,
    /** Search for the text currently typed has finished (not debouncing/fetching). */
    settled: on && debounced === trimmed && !query.isFetching && !query.isPlaceholderData,
    loading: enabled && trimmed.length >= 1 && (debounced !== trimmed || query.isFetching),
    isError: query.isError,
    term: debounced,
  }
}
