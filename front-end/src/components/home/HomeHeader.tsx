'use client'

import { useEffect, useState, type ReactNode } from 'react'
import Link from 'next/link'
import { UserRound } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore, INTL_LOCALES } from '@/store/i18nStore'
import { useAccess } from '@/hooks/useAccess'
import { DEFAULT_TIMEZONE } from '@/lib/utils'
import { SearchButton } from '@/components/search/GlobalSearch'

/** Tracker page header: title + today's date, a search button that opens
 *  the global stock search (also ⌘K / Ctrl+K) and a person icon → /profile. */
export function HomeHeader({ title, greeting, actions }: { title: string; greeting?: string | null; actions?: ReactNode }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const { can } = useAccess()
  const [date, setDate] = useState('')

  // Client-only so the server render never disagrees with the browser's day.
  useEffect(() => {
    setDate(new Date().toLocaleDateString(INTL_LOCALES[locale], {
      weekday: 'long', month: 'long', day: 'numeric', timeZone: DEFAULT_TIMEZONE,
    }))
  }, [locale])

  const iconBtn = 'min-h-[44px] min-w-[44px] rounded-full inline-flex items-center justify-center focus-visible:outline focus-visible:outline-2'
  const iconStyle = { backgroundColor: theme.colors.surfaceAlt, color: theme.colors.text, outlineColor: theme.colors.primary }

  return (
    <header className="flex flex-col gap-3 min-w-0">
      <div className="flex items-start justify-between gap-3 min-w-0">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold" style={{ color: theme.colors.text }}>{title}</h1>
          <p className="text-[13px] mt-0.5 first-letter:uppercase" style={{ color: theme.colors.textSub }}>
            {greeting ? `${greeting} · ` : ''}{date}
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {actions}
          <SearchButton />
          {can('area.profile') && (
            <Link href="/profile" aria-label={t.home.openProfile} className={iconBtn} style={iconStyle}>
              <UserRound size={18} aria-hidden="true" />
            </Link>
          )}
        </div>
      </div>
    </header>
  )
}
