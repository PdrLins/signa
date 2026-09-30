import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { alertsApi, CheckApiError } from '@/lib/api'
import { ApiAccessError } from '@/lib/access'
import type { AlertInput, AlertsResponse } from '@/types/alerts'

export const ALERTS_KEY = ['alerts'] as const

/** GET /alerts?symbol= — the user's price alerts (with distance from the
 *  current price) and the plan's active-alert limit. */
export function useAlerts(symbol: string | null, enabled = true) {
  return useQuery<AlertsResponse, unknown>({
    queryKey: [...ALERTS_KEY, symbol ?? 'all'],
    queryFn: () => alertsApi.list(symbol ?? undefined),
    enabled,
    staleTime: 60_000,
    retry: (count, err) => !(err instanceof CheckApiError || err instanceof ApiAccessError) && count < 1,
  })
}

export function useCreateAlert() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: AlertInput) => alertsApi.create(body),
    onSettled: () => qc.invalidateQueries({ queryKey: ALERTS_KEY }),
  })
}

export function useDeleteAlert() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => alertsApi.remove(id),
    onSettled: () => qc.invalidateQueries({ queryKey: ALERTS_KEY }),
  })
}
