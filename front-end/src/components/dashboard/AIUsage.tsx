'use client'

import { useTheme } from '@/hooks/useTheme'
import { useScans } from '@/hooks/useScans'
import { useI18nStore } from '@/store/i18nStore'
import { Card } from '@/components/ui/Card'
import { ProgressBar } from '@/components/ui/ProgressBar'
import { Skeleton } from '@/components/ui/Skeleton'

export function AIUsage() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const { data: scans, isLoading } = useScans()

  if (isLoading) {
    return (
      <Card>
        <Skeleton width="100%" height={60} />
      </Card>
    )
  }

  if (!scans?.length) return null

  const totalSignals = scans.reduce((sum, s) => sum + s.signals_found, 0)
  const totalGems = scans.reduce((sum, s) => sum + s.gems_found, 0)
  const totalScanned = scans.reduce((sum, s) => sum + s.tickers_scanned, 0)
  const gemRate = totalScanned > 0 ? Math.round((totalGems / totalScanned) * 100) : 0

  return (
    <Card>
      <p className="text-[11px] font-semibold uppercase tracking-wide mb-3" style={{ color: theme.colors.textSub }}>
        {t.scanResults.title}
      </p>
      <p className="text-lg font-bold mb-3" style={{ color: theme.colors.text }}>
        {t.scanResults.signals.replace('{count}', String(totalSignals))}
      </p>
      <div className="space-y-2">
        <div>
          <div className="flex justify-between mb-1">
            <span className="text-[11px]" style={{ color: theme.colors.textSub }}>{t.scanResults.gemsFound}</span>
            <span className="text-[11px] font-semibold" style={{ color: theme.colors.up }}>
              {totalGems}
            </span>
          </div>
          <ProgressBar value={gemRate} color={theme.colors.up} />
        </div>
        <div>
          <div className="flex justify-between mb-1">
            <span className="text-[11px]" style={{ color: theme.colors.textSub }}>{t.scanResults.tickersScanned}</span>
            <span className="text-[11px] font-semibold" style={{ color: theme.colors.primary }}>
              {totalScanned}
            </span>
          </div>
          <ProgressBar value={100} color={theme.colors.primary} />
        </div>
      </div>
    </Card>
  )
}
