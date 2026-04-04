'use client'

import { useTheme } from '@/hooks/useTheme'
import { Card } from '@/components/ui/Card'
import { Briefcase } from 'lucide-react'

export default function PortfolioPage() {
  const theme = useTheme()

  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-bold" style={{ color: theme.colors.text }}>
        Portfolio
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
            Coming soon
          </h2>
          <p className="text-sm max-w-sm leading-relaxed" style={{ color: theme.colors.textSub }}>
            Manual position tracking coming soon. Wealthsimple does not offer a public API for
            automated sync. You will be able to log positions manually in a future update.
          </p>
        </div>
      </Card>
    </div>
  )
}
