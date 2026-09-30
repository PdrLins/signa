'use client'

import Link from 'next/link'
import { Lock } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useAccess } from '@/hooks/useAccess'
import { homePath } from '@/lib/access'
import { interpolate } from '@/lib/utils'

/** Shown instead of a page the user's plan doesn't include. */
export function LockedArea({ feature }: { feature: string }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const { can, minLevel } = useAccess()
  const level = t.access.levels[minLevel(feature)]
  return (
    <section
      aria-labelledby="locked-title"
      className="max-w-md mx-auto mt-16 rounded-2xl p-6 flex flex-col items-center text-center gap-3"
      style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.border}` }}
    >
      <Lock size={28} aria-hidden="true" style={{ color: theme.colors.textSub }} />
      <h1 id="locked-title" className="text-lg font-semibold" style={{ color: theme.colors.text }}>
        {t.access.lockedTitle}
      </h1>
      <p className="text-sm" style={{ color: theme.colors.textSub }}>
        {interpolate(t.access.lockedBody, { level })}
      </p>
      <Link
        href={homePath(can)}
        className="mt-2 min-h-[44px] inline-flex items-center px-4 rounded-xl text-sm font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        style={{ backgroundColor: theme.colors.primary, color: theme.colors.surface, outlineColor: theme.colors.primary }}
      >
        {t.access.goHome}
      </Link>
    </section>
  )
}
