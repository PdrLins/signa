'use client'

import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { Card } from '@/components/ui/Card'
import { Sidebar } from '@/components/layout/Sidebar'
import { Briefcase } from 'lucide-react'

export default function PortfolioPage() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold" style={{ color: theme.colors.text }}>{t.portfolio.title}</h1>
        <p className="text-sm mt-1" style={{ color: theme.colors.textSub }}>{t.portfolio.comingSoonDesc}</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_300px] gap-6 items-start">
        <div className="space-y-5">
          <Card padding="32px">
            <div className="flex flex-col items-center text-center">
              <div
                className="w-14 h-14 rounded-2xl flex items-center justify-center mb-4"
                style={{ backgroundColor: theme.colors.primary + '18' }}
              >
                <Briefcase size={24} style={{ color: theme.colors.primary }} />
              </div>
              <h2 className="text-lg font-bold mb-2" style={{ color: theme.colors.text }}>
                {t.portfolio.comingSoon}
              </h2>
              <p className="text-sm max-w-sm leading-relaxed" style={{ color: theme.colors.textSub }}>
                {t.portfolio.comingSoonDesc}
              </p>
            </div>
          </Card>
        </div>
        <div className="sticky top-6 hidden lg:block">
          <Sidebar />
        </div>
      </div>
    </div>
  )
}
