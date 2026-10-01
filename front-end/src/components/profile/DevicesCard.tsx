'use client'

import { memo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { LogOut, Monitor, Smartphone } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useAuthStore } from '@/store/authStore'
import { useToast } from '@/hooks/useToast'
import { authApi, type AuthSession } from '@/lib/api'
import { fill, shortDate } from '@/lib/insights'
import { isMigrationRequired, trackerErrorText } from '@/lib/trackerErrors'
import { LoadError, SectionCard, useButtonStyles } from '@/components/profile/ui'

const SESSIONS_KEY = ['auth', 'sessions'] as const

/** Profile → Your devices: where the account is signed in (GET /auth/sessions),
 *  with "Sign out" per device and "Sign out everywhere else". Signing out the
 *  current device signs this browser out too. Hidden before migration 017. */
export function DevicesCard() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const td = t.profile.devices
  const toast = useToast()
  const qc = useQueryClient()
  const btn = useButtonStyles()
  const logout = useAuthStore((s) => s.logout)
  const [busy, setBusy] = useState<string | null>(null)
  const q = useQuery<AuthSession[], unknown>({
    queryKey: SESSIONS_KEY,
    queryFn: () => authApi.sessions(),
    staleTime: 30_000,
    retry: false,
  })

  if (isMigrationRequired(q.error)) return null
  const items = q.data ?? []
  const others = items.filter((s) => !s.current).length

  const signOutLocal = () => {
    logout()
    window.location.href = '/login'
  }

  const revoke = async (s: AuthSession) => {
    setBusy(s.id)
    try {
      await authApi.revokeSession(s.id)
      if (s.current) { signOutLocal(); return }
      toast.show(fill(td.signedOut, { device: s.device_name ?? td.unknown }), 'success', 2500)
      qc.invalidateQueries({ queryKey: SESSIONS_KEY })
    } catch (e) {
      toast.show(trackerErrorText(e, t), 'error')
    } finally {
      setBusy(null)
    }
  }

  const revokeOthers = async () => {
    setBusy('others')
    try {
      const r = await authApi.revokeOtherSessions()
      toast.show(fill(td.othersSignedOut, { n: r.revoked }), 'success', 2500)
      qc.invalidateQueries({ queryKey: SESSIONS_KEY })
    } catch (e) {
      toast.show(trackerErrorText(e, t), 'error')
    } finally {
      setBusy(null)
    }
  }

  return (
    <SectionCard title={td.title} subtitle={td.subtitle}
      right={others > 0 ? (
        <button type="button" onClick={revokeOthers} disabled={busy !== null}
          className={btn.secondary.className} style={btn.secondary.style}>
          {td.signOutOthers}
        </button>
      ) : undefined}>
      {q.isLoading && <div className="h-14 rounded-xl animate-pulse" style={{ backgroundColor: theme.colors.surfaceAlt }} />}
      {!!q.error && <LoadError message={trackerErrorText(q.error, t)} onRetry={() => q.refetch()} />}
      {items.length > 0 && (
        <ul className="flex flex-col gap-2">
          {items.map((s) => <DeviceRow key={s.id} s={s} busy={busy === s.id} disabled={busy !== null} onRevoke={revoke} />)}
        </ul>
      )}
    </SectionCard>
  )
}

const DeviceRow = memo(function DeviceRow({ s, busy, disabled, onRevoke }: {
  s: AuthSession
  busy: boolean
  disabled: boolean
  onRevoke: (s: AuthSession) => void
}) {
  const theme = useTheme()
  const t = useI18nStore((st) => st.t)
  const locale = useI18nStore((st) => st.locale)
  const td = t.profile.devices
  const Icon = s.client === 'ios' ? Smartphone : Monitor
  const name = s.device_name ?? td.unknown
  return (
    <li className="flex items-center gap-3 rounded-xl px-3 py-2.5 min-h-[56px] min-w-0" style={{ backgroundColor: theme.colors.surfaceAlt }}>
      <Icon size={18} aria-hidden="true" className="shrink-0" style={{ color: theme.colors.primary }} />
      <div className="min-w-0 flex-1">
        <p className="text-[14px] font-medium truncate flex items-center gap-2" style={{ color: theme.colors.text }}>
          <span className="truncate">{name}</span>
          {s.current && (
            <span className="shrink-0 text-[11px] font-semibold px-2 py-0.5 rounded-full"
              style={{ backgroundColor: theme.colors.primary + '26', color: theme.colors.primary }}>{td.thisDevice}</span>
          )}
        </p>
        <p className="text-[12px]" style={{ color: theme.colors.textSub }}>
          {s.last_used_at ? fill(td.lastUsed, { date: shortDate(s.last_used_at, locale, true) }) : ''}
          {s.created_at ? ` · ${fill(td.since, { date: shortDate(s.created_at, locale, true) })}` : ''}
        </p>
      </div>
      <button type="button" onClick={() => onRevoke(s)} disabled={disabled}
        aria-label={fill(td.signOutAria, { device: name })} title={td.signOut}
        className="shrink-0 min-h-[44px] px-3 rounded-lg text-[13px] font-medium inline-flex items-center gap-1.5 disabled:opacity-50 focus-visible:outline focus-visible:outline-2"
        style={{ color: theme.colors.down, outlineColor: theme.colors.primary }}>
        <LogOut size={15} aria-hidden="true" />{busy ? td.signingOut : td.signOut}
      </button>
    </li>
  )
})
