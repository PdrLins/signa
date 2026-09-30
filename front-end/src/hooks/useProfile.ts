'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { notificationsApi, profileApi, CheckApiError } from '@/lib/api'
import type {
  NotificationPrefsResponse, NotificationPrefsUpdate, Profile, ProfileOptions, ProfileUpdate,
} from '@/types/profile'

export const PROFILE_KEY = ['profile'] as const
export const PROFILE_OPTIONS_KEY = ['profile', 'options'] as const
export const NOTIF_PREFS_KEY = ['notifications', 'prefs'] as const

/** Coded 4xx / 503 (migration_required) answers won't change on retry. */
export function noRetryOnCoded(count: number, err: unknown): boolean {
  if (err instanceof CheckApiError) return false
  return count < 2
}

export function useProfile(enabled = true) {
  return useQuery<Profile, unknown>({
    queryKey: PROFILE_KEY,
    queryFn: () => profileApi.get(),
    staleTime: 60_000,
    enabled,
    retry: noRetryOnCoded,
  })
}

export function useProfileOptions(enabled = true) {
  return useQuery<ProfileOptions, unknown>({
    queryKey: PROFILE_OPTIONS_KEY,
    queryFn: () => profileApi.options(),
    staleTime: 60 * 60_000,
    enabled,
    retry: noRetryOnCoded,
  })
}

/** PUT /profile with an optimistic cache update; rolls back on error. */
export function useUpdateProfile() {
  const qc = useQueryClient()
  return useMutation<Profile, unknown, ProfileUpdate, { previous?: Profile }>({
    mutationFn: (body) => profileApi.update(body),
    onMutate: async (body) => {
      await qc.cancelQueries({ queryKey: PROFILE_KEY, exact: true })
      const previous = qc.getQueryData<Profile>(PROFILE_KEY)
      if (previous) qc.setQueryData<Profile>(PROFILE_KEY, { ...previous, ...body } as Profile)
      return { previous }
    },
    onError: (_e, _body, ctx) => {
      if (ctx?.previous) qc.setQueryData(PROFILE_KEY, ctx.previous)
    },
    onSuccess: (data) => {
      qc.setQueryData(PROFILE_KEY, data)
      // country changes which account types are allowed
      qc.invalidateQueries({ queryKey: ['accounts'] })
    },
  })
}

export function useNotificationPrefs() {
  return useQuery<NotificationPrefsResponse, unknown>({
    queryKey: NOTIF_PREFS_KEY,
    queryFn: () => notificationsApi.getPrefs(),
    staleTime: 60_000,
    retry: noRetryOnCoded,
  })
}

export function useUpdateNotificationPrefs() {
  const qc = useQueryClient()
  return useMutation<NotificationPrefsResponse, unknown, NotificationPrefsUpdate, { previous?: NotificationPrefsResponse }>({
    mutationFn: (body) => notificationsApi.updatePrefs(body),
    onMutate: async (body) => {
      await qc.cancelQueries({ queryKey: NOTIF_PREFS_KEY })
      const previous = qc.getQueryData<NotificationPrefsResponse>(NOTIF_PREFS_KEY)
      if (previous) {
        const prefs = { ...previous.prefs }
        for (const [k, v] of Object.entries(body)) {
          const key = k as keyof typeof prefs
          prefs[key] = { ...prefs[key], ...v }
        }
        qc.setQueryData<NotificationPrefsResponse>(NOTIF_PREFS_KEY, { ...previous, prefs })
      }
      return { previous }
    },
    onError: (_e, _body, ctx) => {
      if (ctx?.previous) qc.setQueryData(NOTIF_PREFS_KEY, ctx.previous)
    },
    onSuccess: (data) => { qc.setQueryData(NOTIF_PREFS_KEY, data) },
  })
}
