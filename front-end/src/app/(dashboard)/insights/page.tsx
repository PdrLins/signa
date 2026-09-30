'use client'

import { Coins, LineChart, PieChart, type LucideIcon } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { HomeHeader } from '@/components/home/HomeHeader'
import { SoonCard } from '@/components/profile/ui'

const ICONS: Record<string, LucideIcon> = { allocation: PieChart, performance: LineChart, income: Coins }

/** Insights — placeholder until the portfolio analytics phase. */
export default function InsightsPage() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  return (
    <div className="space-y-5 pb-4 min-w-0">
      <HomeHeader title={t.insightsPage.title} />
      <p className="text-[14px] max-w-2xl" style={{ color: theme.colors.textSub }}>{t.insightsPage.subtitle}</p>
      <ul className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {t.insightsPage.cards.map((c) => (
          <SoonCard key={c.key} title={c.title} body={c.body} icon={ICONS[c.key]} />
        ))}
      </ul>
      <p className="text-[12px]" style={{ color: theme.colors.textHint }}>{t.tracker.notAdvice}</p>
    </div>
  )
}
