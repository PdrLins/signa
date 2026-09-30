'use client'

import { useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { accountsApi, peopleApi } from '@/lib/api'
import { noRetryOnCoded } from '@/hooks/useProfile'
import { useAccess } from '@/hooks/useAccess'
import type { AccountsResponse, PeopleResponse } from '@/types/accounts'

export const ACCOUNTS_KEY = ['accounts'] as const
export const PEOPLE_KEY = ['people'] as const

/** GET /accounts — 503 migration_required before migration 013. */
export function useAccounts(enabled = true) {
  // Only ask when the plan can open holdings: a 403 would otherwise be
  // re-requested on every mount (errors are never "fresh").
  const { can } = useAccess()
  const allowed = can('area.holdings')
  return useQuery<AccountsResponse, unknown>({
    queryKey: ACCOUNTS_KEY,
    queryFn: () => accountsApi.list(),
    staleTime: 60_000,
    enabled: enabled && allowed,
    retry: noRetryOnCoded,
    refetchOnWindowFocus: false,
  })
}

export function usePeople(enabled = true) {
  // Only ask when the plan can open holdings: a 403 would otherwise be
  // re-requested on every mount (errors are never "fresh").
  const { can } = useAccess()
  const allowed = can('area.holdings')
  return useQuery<PeopleResponse, unknown>({
    queryKey: PEOPLE_KEY,
    queryFn: () => peopleApi.list(),
    staleTime: 60_000,
    enabled: enabled && allowed,
    retry: noRetryOnCoded,
    refetchOnWindowFocus: false,
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
