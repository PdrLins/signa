'use client'

import Link from 'next/link'
import { CalendarDays, Megaphone, Split, type LucideIcon } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useAccess } from '@/hooks/useAccess'
import { HomeHeader } from '@/components/home/HomeHeader'
import { SoonCard, useButtonStyles } from '@/components/profile/ui'

const ICONS: Record<string, LucideIcon> = { dividends: CalendarDays, earnings: Megaphone, events: Split }

/** Coming up — placeholder; the dividend calendar already exists at /dividends. */
export default function ComingUpPage() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const { can } = useAccess()
  const btn = useButtonStyles()
  return (
    <div className="space-y-5 pb-4 min-w-0">
      <HomeHeader title={t.comingUpPage.title} />
      <p className="text-[14px] max-w-2xl" style={{ color: theme.colors.textSub }}>{t.comingUpPage.subtitle}</p>
      <ul className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {t.comingUpPage.cards.map((c) => (
          <SoonCard key={c.key} title={c.title} body={c.body} icon={ICONS[c.key]} />
        ))}
      </ul>
      {can('area.dividends') && (
        <Link href="/dividends" className={btn.secondary.className} style={btn.secondary.style}>
          <CalendarDays size={16} aria-hidden="true" />{t.comingUpPage.seeCalendar}
        </Link>
      )}
    </div>
  )
}
