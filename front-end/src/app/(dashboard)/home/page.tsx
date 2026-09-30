'use client'

import Link from 'next/link'
import { CalendarDays, Coins, LineChart, TrendingUp, Wallet, type LucideIcon } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useAccess } from '@/hooks/useAccess'
import { useProfile } from '@/hooks/useProfile'
import { fill } from '@/lib/insights'
import { HomeHeader } from '@/components/home/HomeHeader'
import { SoonCard, useButtonStyles } from '@/components/profile/ui'

const CARD_ICONS: Record<string, LucideIcon> = { value: Wallet, income: Coins, movers: TrendingUp, next: CalendarDays }

/** Today (tracker home) — placeholder shell; the next phase fills the cards with data. */
export default function HomePage() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const { can } = useAccess()
  const btn = useButtonStyles()
  const profile = useProfile(can('area.profile'))
  const name = profile.data?.display_name?.trim()
  const greeting = name ? fill(t.home.hello, { name }) : t.home.helloAnon

  return (
    <div className="space-y-5 pb-4 min-w-0">
      <HomeHeader title={t.home.title} greeting={greeting} />
      <p className="text-[14px] max-w-2xl" style={{ color: theme.colors.textSub }}>{t.home.intro}</p>
      <ul className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {t.home.cards.map((c) => (
          <SoonCard key={c.key} title={c.title} body={c.body} icon={CARD_ICONS[c.key] ?? LineChart} />
        ))}
      </ul>
      <div className="flex flex-wrap gap-2">
        {can('area.holdings') && (
          <Link href="/holdings" className={btn.primary.className} style={btn.primary.style}>
            <Wallet size={16} aria-hidden="true" />{t.home.goHoldings}
          </Link>
        )}
        {can('area.dividends') && (
          <Link href="/dividends" className={btn.secondary.className} style={btn.secondary.style}>
            <CalendarDays size={16} aria-hidden="true" />{t.home.goDividends}
          </Link>
        )}
      </div>
      <p className="text-[12px]" style={{ color: theme.colors.textHint }}>{t.tracker.notAdvice}</p>
    </div>
  )
}
