'use client'

import { useState, useMemo, useEffect } from 'react'
import { LangSwitcher } from '@/components/ui/LangSwitcher'
import { usePathname } from 'next/navigation'
import Link from 'next/link'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useAccess } from '@/hooks/useAccess'
import {
  LayoutDashboard,
  Activity,
  Briefcase,
  ChartLine,
  Star,
  Settings,
  Menu,
  Brain,
  Plug,
  HelpCircle,
  ScrollText,
  Search,
  Wallet, CalendarDays } from 'lucide-react'
import { isNavActive } from '@/components/layout/LeftNav'

export function BottomNav() {
  const theme = useTheme()
  const pathname = usePathname()
  const t = useI18nStore((s) => s.t)
  const [moreOpen, setMoreOpen] = useState(false)

  const { can } = useAccess()

  // Only what the user's plan includes. The bar keeps up to 4 tabs plus
  // More: when the plan hides some main tabs, allowed More items move up.
  const { TABS, MORE_ITEMS } = useMemo(() => {
    const main = [
      { label: t.nav.today, href: '/today', icon: LayoutDashboard, feature: 'area.today' },
      { label: t.nav.signals, href: '/signals', icon: Activity, feature: 'area.signals' },
      { label: t.nav.holdingsShort, href: '/holdings', icon: Wallet, feature: 'area.holdings' },
      { label: t.nav.dividends, href: '/dividends', icon: CalendarDays, feature: 'area.dividends' },
      { label: t.nav.isItWorkingShort, href: '/performance', icon: ChartLine, feature: 'area.performance' },
    ].filter((i) => can(i.feature))
    const more = [
      { label: t.nav.positions, href: '/positions', icon: Briefcase, feature: 'area.positions' },
      { label: t.nav.check, href: '/check', icon: Search, feature: 'area.check' },
      { label: t.nav.brain, href: '/brain', icon: Brain, feature: 'area.brain' },
      { label: t.nav.watchlist, href: '/watchlist', icon: Star, feature: 'area.watchlist' },
      { label: t.nav.settings, href: '/settings', icon: Settings, feature: 'area.settings' },
      { label: t.nav.integrations, href: '/integrations', icon: Plug, feature: 'area.integrations' },
      { label: t.nav.logs, href: '/logs', icon: ScrollText, feature: 'area.logs' },
      { label: t.nav.howItWorks, href: '/how-it-works', icon: HelpCircle, feature: 'area.how_it_works' },
    ].filter((i) => can(i.feature))
    const shown = main.slice(0, 4)
    const rest = [...main.slice(4), ...more]
    const promoted = rest.slice(0, Math.max(0, 4 - shown.length))
    return {
      TABS: [...shown, ...promoted, { label: t.nav.more, href: '#more', icon: Menu, feature: '' }],
      MORE_ITEMS: rest.slice(promoted.length),
    }
  }, [t, can])

  const moreActive = (href: string) =>
    href === '/brain' || href === '/positions' ? isNavActive(href, pathname) : (pathname === href || pathname.startsWith(href + '/'))

  const isMoreActive = useMemo(
    () => MORE_ITEMS.some((item) => moreActive(item.href)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [MORE_ITEMS, pathname]
  )

  // Escape closes the More sheet
  useEffect(() => {
    if (!moreOpen) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setMoreOpen(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [moreOpen])

  return (
    <>
      {moreOpen && (
        <div
          className="fixed inset-0 z-[60] md:hidden"
          onClick={() => setMoreOpen(false)}
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
            role="dialog"
            aria-label={t.nav.moreNav}
          >
            <div className="grid grid-cols-3 gap-3">
              {MORE_ITEMS.map((item) => {
                const isActive = moreActive(item.href)
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    onClick={() => setMoreOpen(false)}
                    className="flex flex-col items-center gap-1.5 py-3 rounded-xl transition-all"
                    style={{
                      backgroundColor: isActive ? theme.colors.primary + '15' : 'transparent',
                    }}
                    aria-current={isActive ? 'page' : undefined}
                  >
                    <item.icon
                      aria-hidden="true"
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
            <div className="mt-4 pt-4 flex justify-center" style={{ borderTop: `1px solid ${theme.colors.border}` }}>
              <LangSwitcher />
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
        aria-label={t.nav.mainNav}
      >
        <div className="flex items-center justify-around py-2 pb-[max(8px,env(safe-area-inset-bottom))]">
          {TABS.map((tab) => {
            const isMore = tab.href === '#more'
            const isActive = isMore ? isMoreActive || moreOpen : isNavActive(tab.href, pathname)
            const color = isActive ? theme.colors.primary : theme.colors.textSub

            if (isMore) {
              return (
                <button
                  type="button"
                  key={tab.href}
                  onClick={() => setMoreOpen((prev) => !prev)}
                  className="flex flex-col items-center gap-0.5 px-2 py-2 min-w-[56px] rounded-lg focus-visible:outline focus-visible:outline-2"
                  style={{ outlineColor: theme.colors.primary }}
                  aria-label={t.nav.moreNav}
                  aria-expanded={moreOpen}
                >
                  <tab.icon size={20} style={{ color }} aria-hidden="true" />
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
                className="flex flex-col items-center gap-0.5 px-2 py-2 min-w-[56px] rounded-lg focus-visible:outline focus-visible:outline-2"
                style={{ outlineColor: theme.colors.primary }}
                aria-current={isActive ? 'page' : undefined}
                onClick={() => setMoreOpen(false)}
              >
                <tab.icon size={20} style={{ color }} aria-hidden="true" />
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
