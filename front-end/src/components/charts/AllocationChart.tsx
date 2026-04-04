'use client'

import dynamic from 'next/dynamic'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { Card } from '@/components/ui/Card'
import { Skeleton } from '@/components/ui/Skeleton'

const PieChart = dynamic(
  () => import('recharts').then((mod) => mod.PieChart),
  { ssr: false }
)
const Pie = dynamic(
  () => import('recharts').then((mod) => mod.Pie),
  { ssr: false }
)
const Cell = dynamic(
  () => import('recharts').then((mod) => mod.Cell),
  { ssr: false }
)
const ResponsiveContainer = dynamic(
  () => import('recharts').then((mod) => mod.ResponsiveContainer),
  { ssr: false }
)

interface AllocationChartProps {
  safeCount: number
  riskCount: number
  isLoading?: boolean
}

export function AllocationChart({ safeCount, riskCount, isLoading }: AllocationChartProps) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)

  if (isLoading) {
    return (
      <Card>
        <Skeleton width="100%" height={220} borderRadius={14} />
      </Card>
    )
  }

  const total = safeCount + riskCount
  const data = [
    { name: t.charts.safeIncome, value: safeCount },
    { name: t.charts.highRisk, value: riskCount },
  ]
  const colors = [theme.colors.up, theme.colors.primary]
  const safePct = total > 0 ? Math.round((safeCount / total) * 100) : 0
  const riskPct = total > 0 ? 100 - safePct : 0

  return (
    <Card>
      <p
        className="text-[11px] font-semibold uppercase tracking-wide mb-4"
        style={{ color: theme.colors.textSub }}
      >
        {t.charts.allocation}
      </p>

      <div className="flex items-center justify-center">
        <div className="relative" style={{ width: 180, height: 180 }}>
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={data}
                cx="50%"
                cy="50%"
                innerRadius={55}
                outerRadius={80}
                paddingAngle={3}
                dataKey="value"
                strokeWidth={0}
              >
                {data.map((_, index) => (
                  <Cell key={index} fill={colors[index]} />
                ))}
              </Pie>
            </PieChart>
          </ResponsiveContainer>
          {/* Center label */}
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className="text-2xl font-bold" style={{ color: theme.colors.text }}>
              {total}
            </span>
            <span className="text-[10px]" style={{ color: theme.colors.textSub }}>
              {t.charts.total}
            </span>
          </div>
        </div>
      </div>

      {/* Legend */}
      <div className="flex justify-center gap-6 mt-4">
        <div className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: theme.colors.up }} />
          <span className="text-xs" style={{ color: theme.colors.text }}>
            {t.charts.safeIncome}
          </span>
          <span className="text-xs font-bold" style={{ color: theme.colors.up }}>
            {safePct}%
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: theme.colors.primary }} />
          <span className="text-xs" style={{ color: theme.colors.text }}>
            {t.charts.highRisk}
          </span>
          <span className="text-xs font-bold" style={{ color: theme.colors.primary }}>
            {riskPct}%
          </span>
        </div>
      </div>
    </Card>
  )
}
