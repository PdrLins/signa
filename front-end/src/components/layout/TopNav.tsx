'use client'

import { useEffect, useState } from 'react'
import { usePathname } from 'next/navigation'
import Link from 'next/link'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { ThemeSwitcher } from '@/components/ui/ThemeSwitcher'
import { LangSwitcher } from '@/components/ui/LangSwitcher'
import { DEFAULT_TIMEZONE } from '@/lib/utils'

export function TopNav() {
  const theme = useTheme()
  const pathname = usePathname()
  const t = useI18nStore((s) => s.t)

  const NAV_ITEMS = [
    { label: t.nav.overview, href: '/overview' },
    { label: t.nav.signals, href: '/signals' },
    { label: t.nav.watchlist, href: '/watchlist' },
    { label: t.nav.portfolio, href: '/portfolio' },
    { label: t.nav.howItWorks, href: '/how-it-works' },
  ]
  const [time, setTime] = useState<Date | null>(null)

  useEffect(() => {
    setTime(new Date())
    const interval = setInterval(() => setTime(new Date()), 1000)
    return () => clearInterval(interval)
  }, [])

  return (
    <nav
      className="sticky top-0 z-50 px-4 py-3"
      style={{
        backgroundColor: theme.colors.surface,
        borderBottom: `0.5px solid ${theme.colors.border}`,
        backdropFilter: 'blur(20px)',
      }}
    >
      <div className="max-w-[1280px] mx-auto flex items-center justify-between">
        {/* Logo */}
        <div className="flex items-center gap-2">
          <div
            className="w-8 h-8 rounded-lg flex items-center justify-center text-xs font-bold text-white"
            style={{ backgroundColor: theme.colors.primary }}
          >
            S
          </div>
          <span className="text-base font-bold hidden sm:block" style={{ color: theme.colors.text }}>
            Signa
          </span>
        </div>

        {/* Nav pills */}
        <div
          className="hidden md:flex items-center gap-1 rounded-xl px-1 py-1"
          style={{ backgroundColor: theme.colors.nav }}
        >
          {NAV_ITEMS.map((item) => {
            const isActive = pathname === item.href
            return (
              <Link
                key={item.href}
                href={item.href}
                className="px-4 py-1.5 rounded-lg text-sm font-medium transition-all"
                style={{
                  backgroundColor: isActive ? theme.colors.navActive : 'transparent',
                  color: isActive ? theme.colors.text : theme.colors.textSub,
                  boxShadow: isActive ? (theme.isDark ? '0 1px 3px rgba(0,0,0,0.3)' : '0 1px 3px rgba(0,0,0,0.08)') : 'none',
                }}
              >
                {item.label}
              </Link>
            )
          })}
        </div>

        {/* Right side */}
        <div className="hidden md:flex items-center gap-3">
          <span className="text-xs tabular-nums" style={{ color: theme.colors.textSub }}>
            {time ? time.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', second: '2-digit', timeZone: DEFAULT_TIMEZONE }) : '\u00A0'}
          </span>
          <LangSwitcher />
          <ThemeSwitcher compact />
        </div>
      </div>
    </nav>
  )
}
