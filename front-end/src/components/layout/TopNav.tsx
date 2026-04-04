'use client'

import { useEffect, useState } from 'react'
import { usePathname } from 'next/navigation'
import Link from 'next/link'
import { useTheme } from '@/hooks/useTheme'
import { ThemeSwitcher } from '@/components/ui/ThemeSwitcher'

const NAV_ITEMS = [
  { label: 'Overview', href: '/overview' },
  { label: 'Signals', href: '/signals' },
  { label: 'Watchlist', href: '/watchlist' },
  { label: 'Portfolio', href: '/portfolio' },
]

export function TopNav() {
  const theme = useTheme()
  const pathname = usePathname()
  const [time, setTime] = useState(new Date())

  useEffect(() => {
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
      <div className="max-w-[1080px] mx-auto flex items-center justify-between">
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
        <div className="hidden md:flex items-center gap-4">
          <span className="text-xs tabular-nums" style={{ color: theme.colors.textSub }}>
            {time.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', second: '2-digit', timeZone: 'America/Toronto' })}
          </span>
          <ThemeSwitcher compact />
        </div>
      </div>
    </nav>
  )
}
