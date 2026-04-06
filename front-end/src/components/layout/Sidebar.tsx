'use client'

import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useAllSignals } from '@/hooks/useSignals'
import { WatchlistTable } from '@/components/watchlist/WatchlistTable'
import { BrainPerformanceWidget } from '@/components/dashboard/DashboardWidgets'
import { Card } from '@/components/ui/Card'

export function Sidebar() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const { data: signals } = useAllSignals({ limit: 200 })

  return (
    <aside className="hidden lg:flex flex-col gap-3 w-[300px] shrink-0">
      <Card>
        <h3 className="text-[11px] font-semibold uppercase tracking-wide mb-2" style={{ color: theme.colors.textSub }}>
          {t.overview.watchlist}
        </h3>
        <WatchlistTable signals={signals} compact />
      </Card>
      <BrainPerformanceWidget />
    </aside>
  )
}
