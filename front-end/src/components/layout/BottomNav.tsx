'use client'

import { usePathname } from 'next/navigation'
import Link from 'next/link'
import { useTheme } from '@/hooks/useTheme'
import { LayoutDashboard, TrendingUp, Star, Briefcase } from 'lucide-react'

const TABS = [
  { label: 'Overview', href: '/overview', icon: LayoutDashboard },
  { label: 'Signals', href: '/signals', icon: TrendingUp },
  { label: 'Watchlist', href: '/watchlist', icon: Star },
  { label: 'Portfolio', href: '/portfolio', icon: Briefcase },
]

export function BottomNav() {
  const theme = useTheme()
  const pathname = usePathname()

  return (
    <nav
      className="fixed bottom-0 left-0 right-0 z-50 md:hidden"
      style={{
        backgroundColor: theme.colors.surface + 'E6',
        borderTop: `0.5px solid ${theme.colors.border}`,
        backdropFilter: 'blur(20px)',
        WebkitBackdropFilter: 'blur(20px)',
      }}
    >
      <div className="flex items-center justify-around py-2 pb-[max(8px,env(safe-area-inset-bottom))]">
        {TABS.map((tab) => {
          const isActive = pathname === tab.href
          const color = isActive ? theme.colors.primary : theme.colors.textSub

          return (
            <Link
              key={tab.href}
              href={tab.href}
              className="flex flex-col items-center gap-0.5 px-3 py-1"
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
  )
}
