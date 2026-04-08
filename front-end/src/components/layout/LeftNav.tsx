'use client'

import { usePathname } from 'next/navigation'
import Link from 'next/link'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useAuthStore } from '@/store/authStore'
import {
  LayoutDashboard,
  TrendingUp,
  Star,
  HelpCircle,
  Settings,
  Brain,
  ScrollText,
  Plug,
  Activity,
  LogOut,
} from 'lucide-react'

export function LeftNav() {
  const theme = useTheme()
  const pathname = usePathname()
  const t = useI18nStore((s) => s.t)
  const logout = useAuthStore((s) => s.logout)

  const NAV_ITEMS = [
    { label: t.nav.overview, href: '/overview', icon: LayoutDashboard },
    { label: t.nav.signals, href: '/signals', icon: TrendingUp },
    { label: t.nav.watchlist, href: '/watchlist', icon: Star },
    // TODO: Uncomment when portfolio manual tracking is implemented
    // { label: t.nav.portfolio, href: '/portfolio', icon: Briefcase },
    { label: t.nav.brain, href: '/brain', icon: Brain },
    { label: t.nav.brainPerformance, href: '/brain/performance', icon: Activity },
    { label: t.nav.logs, href: '/logs', icon: ScrollText },
    { label: t.nav.integrations, href: '/integrations', icon: Plug },
    { label: t.nav.howItWorks, href: '/how-it-works', icon: HelpCircle },
    { label: t.nav.settings, href: '/settings', icon: Settings },
  ]

  return (
    <nav
      className="hidden md:flex flex-col items-center fixed left-5 top-1/2 -translate-y-1/2 z-50 py-3 px-1.5 gap-1 rounded-2xl"
      style={{
        backgroundColor: theme.colors.surface,
        border: `1px solid ${theme.colors.border}`,
        boxShadow: theme.isDark
          ? '0 4px 24px rgba(0,0,0,0.4)'
          : '0 4px 24px rgba(0,0,0,0.08)',
      }}
    >
      {NAV_ITEMS.map((item, i) => {
        const isActive = pathname === item.href || (item.href === '/signals' && pathname.startsWith('/signals/'))
        const isLast = i === NAV_ITEMS.length - 1
        return (
          <div key={item.href}>
            {/* Separator before settings */}
            {isLast && (
              <div
                className="w-6 h-px mx-auto mb-1"
                style={{ backgroundColor: theme.colors.border }}
              />
            )}
            <Link
              href={item.href}
              className="flex items-center justify-center w-10 h-10 rounded-xl transition-all"
              style={{
                backgroundColor: isActive ? theme.colors.primary + '15' : 'transparent',
                color: isActive ? theme.colors.primary : theme.colors.textSub,
              }}
              title={item.label}
            >
              <item.icon size={20} strokeWidth={isActive ? 2.2 : 1.8} />
            </Link>
          </div>
        )
      })}

      {/* Logout */}
      <div
        className="w-6 h-px mx-auto my-1"
        style={{ backgroundColor: theme.colors.border }}
      />
      <button
        onClick={() => {
          logout()
          window.location.href = '/login'
        }}
        className="flex items-center justify-center w-10 h-10 rounded-xl transition-all hover:opacity-80"
        style={{ color: theme.colors.down }}
        title={t.settings.logOut}
      >
        <LogOut size={18} strokeWidth={1.8} />
      </button>
    </nav>
  )
}
