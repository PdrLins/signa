'use client'

import { useState, useMemo } from 'react'
import { usePathname } from 'next/navigation'
import Link from 'next/link'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import {
  LayoutDashboard,
  TrendingUp,
  Star,
  Briefcase,
  Settings,
  Menu,
  Brain,
  Activity,
  Plug,
  HelpCircle,
  ScrollText,
} from 'lucide-react'

export function BottomNav() {
  const theme = useTheme()
  const pathname = usePathname()
  const t = useI18nStore((s) => s.t)
  const [moreOpen, setMoreOpen] = useState(false)

  const MORE_ITEMS = useMemo(() => [
    { label: t.nav.brain, href: '/brain', icon: Brain },
    { label: t.nav.brainPerformance, href: '/brain/performance', icon: Activity },
    { label: t.nav.integrations, href: '/integrations', icon: Plug },
    { label: t.nav.howItWorks, href: '/how-it-works', icon: HelpCircle },
    { label: t.nav.logs, href: '/logs', icon: ScrollText },
    { label: t.nav.settings, href: '/settings', icon: Settings },
  ], [t])

  const TABS = useMemo(() => [
    { label: t.nav.overview, href: '/overview', icon: LayoutDashboard },
    { label: t.nav.signals, href: '/signals', icon: TrendingUp },
    { label: t.nav.watchlist, href: '/watchlist', icon: Star },
    { label: t.nav.portfolio, href: '/portfolio', icon: Briefcase },
    { label: 'More', href: '#more', icon: Menu },
  ], [t])

  const isMoreActive = useMemo(
    () => MORE_ITEMS.some((item) => pathname === item.href || pathname.startsWith(item.href + '/')),
    [MORE_ITEMS, pathname]
  )

  return (
    <>
      {moreOpen && (
        <div
          className="fixed inset-0 z-[60] md:hidden"
          onClick={() => setMoreOpen(false)}
          aria-label="Close more menu"
        >
          <div
            className="absolute bottom-[72px] left-0 right-0 rounded-t-2xl p-4 pb-6 animate-in slide-in-from-bottom duration-200"
            style={{
              backgroundColor: theme.colors.surface,
              borderTop: `1px solid ${theme.colors.border}`,
              boxShadow: theme.isDark
                ? '0 -8px 24px rgba(0,0,0,0.4)'
                : '0 -8px 24px rgba(0,0,0,0.1)',
            }}
            onClick={(e) => e.stopPropagation()}
            role="menu"
            aria-label="Additional navigation"
          >
            <div className="grid grid-cols-3 gap-3">
              {MORE_ITEMS.map((item) => {
                const isActive = pathname === item.href || pathname.startsWith(item.href + '/')
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    onClick={() => setMoreOpen(false)}
                    className="flex flex-col items-center gap-1.5 py-3 rounded-xl transition-all"
                    style={{
                      backgroundColor: isActive ? theme.colors.primary + '15' : 'transparent',
                    }}
                    role="menuitem"
                    aria-label={item.label}
                  >
                    <item.icon
                      size={20}
                      style={{ color: isActive ? theme.colors.primary : theme.colors.textSub }}
                    />
                    <span
                      className="text-[10px] font-medium"
                      style={{ color: isActive ? theme.colors.primary : theme.colors.textSub }}
                    >
                      {item.label}
                    </span>
                  </Link>
                )
              })}
            </div>
          </div>
        </div>
      )}

      <nav
        className="fixed bottom-0 left-0 right-0 z-50 md:hidden"
        style={{
          backgroundColor: theme.colors.surface.startsWith('#')
            ? theme.colors.surface + 'E6'
            : theme.colors.surface,
          borderTop: `0.5px solid ${theme.colors.border}`,
          backdropFilter: 'blur(20px)',
          WebkitBackdropFilter: 'blur(20px)',
        }}
        aria-label="Main navigation"
      >
        <div className="flex items-center justify-around py-2 pb-[max(8px,env(safe-area-inset-bottom))]">
          {TABS.map((tab) => {
            const isMore = tab.href === '#more'
            const isActive = isMore ? isMoreActive || moreOpen : pathname === tab.href
            const color = isActive ? theme.colors.primary : theme.colors.textSub

            if (isMore) {
              return (
                <button
                  key={tab.href}
                  onClick={() => setMoreOpen((prev) => !prev)}
                  className="flex flex-col items-center gap-0.5 px-3 py-2"
                  aria-label="More navigation options"
                  aria-expanded={moreOpen}
                >
                  <tab.icon size={20} style={{ color }} />
                  <span className="text-[10px] font-medium" style={{ color }}>
                    {tab.label}
                  </span>
                </button>
              )
            }

            return (
              <Link
                key={tab.href}
                href={tab.href}
                className="flex flex-col items-center gap-0.5 px-3 py-2"
                aria-label={tab.label}
                onClick={() => setMoreOpen(false)}
              >
                <tab.icon size={20} style={{ color }} />
                <span className="text-[10px] font-medium" style={{ color }}>
                  {tab.label}
                </span>
              </Link>
            )
          })}
        </div>
      </nav>
    </>
  )
}
