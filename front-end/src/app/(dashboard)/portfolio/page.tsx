'use client'

import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { Card } from '@/components/ui/Card'
import { Briefcase } from 'lucide-react'

export default function PortfolioPage() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)

  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-bold" style={{ color: theme.colors.text }}>
        {t.portfolio.title}
      </h1>

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
  )
}
