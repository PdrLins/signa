'use client'

import Link from 'next/link'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useAccess } from '@/hooks/useAccess'
import { Plug, ScrollText, HelpCircle, Star, ChevronRight } from 'lucide-react'

/** Onward links from Settings to the pages that left the main nav. */
export function SettingsLinks() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const { can } = useAccess()
  const links = [
    { feature: 'area.integrations', href: '/integrations', label: t.nav.integrations, desc: t.settingsLinks.integrations, icon: Plug },
    { feature: 'area.logs', href: '/logs', label: t.nav.logs, desc: t.settingsLinks.logs, icon: ScrollText },
    { feature: 'area.how_it_works', href: '/how-it-works', label: t.settingsLinks.howItWorksTitle, desc: t.settingsLinks.howItWorks, icon: HelpCircle },
    { feature: 'area.watchlist', href: '/watchlist', label: t.nav.watchlist, desc: t.settingsLinks.watchlist, icon: Star },
  ].filter((l) => can(l.feature))
  return (
    <nav aria-label={t.settingsLinks.label} className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
      {links.map((l) => (
        <Link
          key={l.href}
          href={l.href}
          className="flex items-center gap-3 rounded-[14px] p-4 transition-opacity hover:opacity-90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          style={{
            backgroundColor: theme.colors.surface,
            border: `1px solid ${theme.colors.border}`,
            outlineColor: theme.colors.primary,
          }}
        >
          <l.icon size={18} aria-hidden="true" style={{ color: theme.colors.primary }} />
          <span className="min-w-0 flex-1">
            <span className="block text-sm font-semibold" style={{ color: theme.colors.text }}>{l.label}</span>
            <span className="block text-xs mt-0.5" style={{ color: theme.colors.textSub }}>{l.desc}</span>
          </span>
          <ChevronRight size={16} aria-hidden="true" style={{ color: theme.colors.textSub }} />
        </Link>
      ))}
    </nav>
  )
}
