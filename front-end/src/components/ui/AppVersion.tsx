'use client'

import { useQuery } from '@tanstack/react-query'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { healthApi } from '@/lib/api'
import { fill } from '@/lib/insights'

/** "Web 1.0.3 · Server 1.0.3": the web app's version (package.json, baked in
 *  at build) and the back-end's (GET /version). Both are bumped on every
 *  commit by .githooks/pre-commit. */
export function AppVersion({ className = '' }: { className?: string }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const q = useQuery({ queryKey: ['app', 'version'], queryFn: () => healthApi.version(), staleTime: 5 * 60_000, retry: false })
  const web = process.env.NEXT_PUBLIC_APP_VERSION ?? '—'
  const server = q.data?.backend ?? (q.isError ? '—' : '…')
  return (
    <p className={`text-[12px] tabular-nums ${className}`} style={{ color: theme.colors.textHint }}>
      {fill(t.app.versions, { web, server })}
    </p>
  )
}
