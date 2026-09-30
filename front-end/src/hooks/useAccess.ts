import { useCallback, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { authApi } from '@/lib/api'
import { useAuthStore } from '@/store/authStore'
import type { AccessLevel, MeResponse } from '@/types/access'

/** The signed-in user's level, allowed features and slots (GET /auth/me).
 *  Refetched every minute and on focus, so a level changed in the database
 *  shows up without logging out. */
export function useMe() {
  const token = useAuthStore((s) => s.token)
  return useQuery<MeResponse>({
    queryKey: ['auth', 'me', token],
    queryFn: () => authApi.me(),
    enabled: !!token,
    staleTime: 60_000,
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
  })
}

export function useAccess() {
  const { data, isLoading, isError } = useMe()
  const features = useMemo(() => new Set(data?.features ?? []), [data])
  const minLevels = useMemo(
    () => new Map((data?.catalog ?? []).map((f) => [f.key, f.min_level] as const)),
    [data],
  )
  /** Fails closed: nothing is allowed until /auth/me has answered. */
  const can = useCallback((feature: string) => features.has(feature), [features])
  const minLevel = useCallback(
    (feature: string): AccessLevel => minLevels.get(feature) ?? 'owner',
    [minLevels],
  )
  return {
    me: data,
    level: data?.access_level,
    slots: data?.slots,
    ready: !!data,
    isLoading,
    isError,
    can,
    minLevel,
  }
}
