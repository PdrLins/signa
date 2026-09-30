'use client'

import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { transactionsApi } from '@/lib/api'
import { noRetryOnCoded } from '@/hooks/useProfile'
import type { TransactionFilters, TransactionsResponse } from '@/types/transactions'

export const TRANSACTIONS_KEY = ['transactions'] as const

/** GET /transactions (newest first) with filters and paging. */
export function useTransactions(filters: TransactionFilters) {
  return useQuery<TransactionsResponse, unknown>({
    queryKey: [...TRANSACTIONS_KEY, filters],
    queryFn: () => transactionsApi.list(filters),
    staleTime: 30_000,
    placeholderData: keepPreviousData,
    retry: noRetryOnCoded,
  })
}
