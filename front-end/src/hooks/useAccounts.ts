'use client'

import { useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { accountsApi, peopleApi } from '@/lib/api'
import { noRetryOnCoded } from '@/hooks/useProfile'
import type { AccountsResponse, PeopleResponse } from '@/types/accounts'

export const ACCOUNTS_KEY = ['accounts'] as const
export const PEOPLE_KEY = ['people'] as const

/** GET /accounts — 503 migration_required before migration 013. */
export function useAccounts(enabled = true) {
  return useQuery<AccountsResponse, unknown>({
    queryKey: ACCOUNTS_KEY,
    queryFn: () => accountsApi.list(),
    staleTime: 60_000,
    enabled,
    retry: noRetryOnCoded,
  })
}

export function usePeople(enabled = true) {
  return useQuery<PeopleResponse, unknown>({
    queryKey: PEOPLE_KEY,
    queryFn: () => peopleApi.list(),
    staleTime: 60_000,
    enabled,
    retry: noRetryOnCoded,
  })
}

/** Refresh everything an account change touches (accounts, people counts,
 *  holdings with their account names, transactions). */
export function useInvalidateAccounts() {
  const qc = useQueryClient()
  return useCallback(() => {
    qc.invalidateQueries({ queryKey: ACCOUNTS_KEY })
    qc.invalidateQueries({ queryKey: PEOPLE_KEY })
    qc.invalidateQueries({ queryKey: ['holdings'] })
    qc.invalidateQueries({ queryKey: ['transactions'] })
  }, [qc])
}
