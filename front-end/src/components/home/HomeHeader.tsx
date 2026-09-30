'use client'

import { useCallback, useEffect, useId, useState, type ReactNode } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { Search, UserRound, X } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore, INTL_LOCALES } from '@/store/i18nStore'
import { useAccess } from '@/hooks/useAccess'
import { DEFAULT_TIMEZONE } from '@/lib/utils'
import { SymbolCombobox, resolveRawEntry } from '@/components/check/SymbolCombobox'
import type { SymbolMatch } from '@/types/symbols'

/** Tracker page header: title + today's date, a search button that opens
 *  the stock search (→ the free stock page) and a person icon → /profile. */
export function HomeHeader({ title, greeting, actions }: { title: string; greeting?: string | null; actions?: ReactNode }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const router = useRouter()
  const { can } = useAccess()
  const inputId = useId()
  const [date, setDate] = useState('')
  const [searchOpen, setSearchOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SymbolMatch[]>([])

  // Client-only so the server render never disagrees with the browser's day.
  useEffect(() => {
    setDate(new Date().toLocaleDateString(INTL_LOCALES[locale], {
      weekday: 'long', month: 'long', day: 'numeric', timeZone: DEFAULT_TIMEZONE,
    }))
  }, [locale])

  const go = useCallback((symbol: string) => {
    const s = symbol.trim().toUpperCase()
    if (!s) return
    setSearchOpen(false)
    setQuery('')
    router.push(`/stocks/${encodeURIComponent(s)}`)
  }, [router])

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
          {can('area.stock') && (
            <button type="button" onClick={() => setSearchOpen((o) => !o)} aria-expanded={searchOpen}
              aria-controls={searchOpen ? inputId : undefined}
              aria-label={searchOpen ? t.home.closeSearch : t.home.search} className={iconBtn} style={iconStyle}>
              {searchOpen ? <X size={18} aria-hidden="true" /> : <Search size={18} aria-hidden="true" />}
            </button>
          )}
          {can('area.profile') && (
            <Link href="/profile" aria-label={t.home.openProfile} className={iconBtn} style={iconStyle}>
              <UserRound size={18} aria-hidden="true" />
            </Link>
          )}
        </div>
      </div>
      {searchOpen && (
        <form role="search" aria-label={t.home.search} className="relative"
          onSubmit={(e) => { e.preventDefault(); go(resolveRawEntry(query, results)) }}>
          <div className="relative flex items-center gap-2 rounded-xl px-3"
            style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.border}` }}>
            <Search size={16} aria-hidden="true" style={{ color: theme.colors.textHint }} />
            <SymbolCombobox id={inputId} value={query} onChange={setQuery} onPick={(m) => go(m.symbol)}
              onResults={setResults} placeholder={t.home.searchPlaceholder} ariaLabel={t.home.search}
              className="bg-transparent outline-0 min-w-0 flex-1 h-11 text-[16px] md:text-[14px]" />
          </div>
        </form>
      )}
    </header>
  )
}
