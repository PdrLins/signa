'use client'

import { memo, useState, useMemo, useEffect } from 'react'
import { LangSwitcher } from '@/components/ui/LangSwitcher'
import { ViewAsSwitch } from '@/components/dev/ViewAsSwitch'
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
  CalendarClock,
  Settings,
  Menu,
  Brain,
  Plug,
  HelpCircle,
  ScrollText,
  Search,
  Wallet,
  CalendarDays,
  Sun,
  UserRound,
} from 'lucide-react'
import { isNavActive, type NavItem } from '@/components/layout/LeftNav'

const MoreLink = memo(function MoreLink({ item, active, onClose }: { item: NavItem; active: boolean; onClose: () => void }) {
  const theme = useTheme()
  const color = active ? theme.colors.primary : theme.colors.textSub
  return (
    <Link
      href={item.href}
      onClick={onClose}
      className="flex flex-col items-center gap-1.5 py-3 min-h-[44px] rounded-xl transition-all focus-visible:outline focus-visible:outline-2"
      style={{ backgroundColor: active ? theme.colors.primary + '15' : 'transparent', outlineColor: theme.colors.primary }}
      aria-current={active ? 'page' : undefined}
    >
      <item.icon aria-hidden="true" size={20} style={{ color }} />
      <span className="text-[10px] font-medium text-center" style={{ color }}>{item.label}</span>
    </Link>
  )
})

export function BottomNav() {
  const theme = useTheme()
  const pathname = usePathname()
  const t = useI18nStore((s) => s.t)
  const [moreOpen, setMoreOpen] = useState(false)

  const { can } = useAccess()

  // Only what the user's plan includes. The bar keeps up to 4 tracker tabs
  // plus More; if the plan hides a tab, the first More items move up. The
  // More sheet lists the rest, with the brain pages under their own heading.
  const { TABS, MORE_ITEMS, BRAIN_ITEMS } = useMemo(() => {
    const main: NavItem[] = [
      { label: t.nav.home, href: '/home', icon: Sun, feature: 'area.home' },
      { label: t.nav.holdingsShort, href: '/holdings', icon: Wallet, feature: 'area.holdings' },
      { label: t.nav.following, href: '/following', icon: Star, feature: 'area.watchlist' },
      { label: t.nav.dividends, href: '/dividends', icon: CalendarDays, feature: 'area.dividends' },
    ].filter((i) => can(i.feature))
    const more: NavItem[] = [
      { label: t.nav.profile, href: '/profile', icon: UserRound, feature: 'area.profile' },
      { label: t.nav.comingUp, href: '/coming-up', icon: CalendarClock, feature: 'area.coming_up' },
      { label: t.nav.howItWorks, href: '/how-it-works', icon: HelpCircle, feature: 'area.how_it_works' },
    ].filter((i) => can(i.feature))
    const brain: NavItem[] = [
      { label: t.nav.brainToday, href: '/today', icon: LayoutDashboard, feature: 'area.today' },
      { label: t.nav.signals, href: '/signals', icon: Activity, feature: 'area.signals' },
      { label: t.nav.check, href: '/check', icon: Search, feature: 'area.check' },
      { label: t.nav.positions, href: '/positions', icon: Briefcase, feature: 'area.positions' },
      { label: t.nav.isItWorkingShort, href: '/performance', icon: ChartLine, feature: 'area.performance' },
      { label: t.nav.brain, href: '/brain', icon: Brain, feature: 'area.brain' },
      { label: t.nav.brainSettings, href: '/brain/settings', icon: Settings, feature: 'area.brain' },
      { label: t.nav.integrations, href: '/integrations', icon: Plug, feature: 'area.integrations' },
      { label: t.nav.logs, href: '/logs', icon: ScrollText, feature: 'area.logs' },
    ].filter((i) => can(i.feature))
    const shown = main.slice(0, 4)
    const promoted = more.slice(0, Math.max(0, 4 - shown.length))
    return {
      TABS: [...shown, ...promoted, { label: t.nav.more, href: '#more', icon: Menu, feature: '' }],
      MORE_ITEMS: more.slice(promoted.length),
      BRAIN_ITEMS: brain,
    }
  }, [t, can])

  const moreActive = (href: string) =>
    href === '/brain' || href === '/positions' || href === '/brain/settings' ? isNavActive(href, pathname) : (pathname === href || pathname.startsWith(href + '/'))


  const isMoreActive = useMemo(
    () => [...MORE_ITEMS, ...BRAIN_ITEMS].some((item) => moreActive(item.href)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [MORE_ITEMS, BRAIN_ITEMS, pathname]
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
            className="absolute bottom-[72px] left-0 right-0 rounded-t-2xl p-4 pb-6 max-h-[calc(100vh-96px)] overflow-y-auto animate-in slide-in-from-bottom duration-200"
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
            <ul className="grid grid-cols-3 gap-3">
              {MORE_ITEMS.map((item) => (
                <li key={item.href}>
                  <MoreLink item={item} active={moreActive(item.href)} onClose={() => setMoreOpen(false)} />
                </li>
              ))}
            </ul>
            {BRAIN_ITEMS.length > 0 && (
              <section aria-labelledby="more-brain" className="mt-4 pt-3" style={{ borderTop: `1px solid ${theme.colors.border}` }}>
                <h2 id="more-brain" className="text-[11px] font-semibold uppercase tracking-wide mb-2" style={{ color: theme.colors.textHint }}>
                  {t.nav.brainGroup}
                </h2>
                <ul className="grid grid-cols-3 gap-3">
                  {BRAIN_ITEMS.map((item) => (
                    <li key={item.href}>
                      <MoreLink item={item} active={moreActive(item.href)} onClose={() => setMoreOpen(false)} />
                    </li>
                  ))}
                </ul>
              </section>
            )}
            <div className="mt-4 pt-4 flex flex-wrap items-center justify-center gap-3" style={{ borderTop: `1px solid ${theme.colors.border}` }}>
              <LangSwitcher />
              <ViewAsSwitch variant="inline" />
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
