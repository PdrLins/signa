'use client'

import { useTheme } from '@/hooks/useTheme'
import { useGemSignals } from '@/hooks/useSignals'
import { useI18nStore } from '@/store/i18nStore'
import { ProgressBar } from '@/components/ui/ProgressBar'
import { Card } from '@/components/ui/Card'
import { Skeleton } from '@/components/ui/Skeleton'

export function BucketSplit() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const { data: signals, isLoading } = useGemSignals()

  if (isLoading) {
    return (
      <Card>
        <Skeleton width="100%" height={60} />
      </Card>
    )
  }

  const safeCount = signals?.filter((s) => s.bucket === 'SAFE_INCOME').length ?? 0
  const riskCount = signals?.filter((s) => s.bucket === 'HIGH_RISK').length ?? 0
  const total = safeCount + riskCount || 1
  const safePct = Math.round((safeCount / total) * 100)
  const riskPct = 100 - safePct

  return (
    <Card>
      <p className="text-[11px] font-semibold uppercase tracking-wide mb-3" style={{ color: theme.colors.textSub }}>
        {t.bucket.title}
      </p>
      <div className="space-y-2.5">
        <div>
          <div className="flex justify-between mb-1">
            <span className="text-xs" style={{ color: theme.colors.text }}>{t.bucket.safeIncome}</span>
            <span className="text-xs font-bold" style={{ color: theme.colors.up }}>{safePct}%</span>
          </div>
          <ProgressBar value={safePct} color={theme.colors.up} />
        </div>
        <div>
          <div className="flex justify-between mb-1">
            <span className="text-xs" style={{ color: theme.colors.text }}>{t.bucket.highRisk}</span>
            <span className="text-xs font-bold" style={{ color: theme.colors.primary }}>{riskPct}%</span>
          </div>
          <ProgressBar value={riskPct} color={theme.colors.primary} />
        </div>
      </div>
    </Card>
  )
}
