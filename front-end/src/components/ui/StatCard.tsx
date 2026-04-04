'use client'

import { useTheme } from '@/hooks/useTheme'
import { SparkLine } from '@/components/ui/SparkLine'

interface StatCardProps {
  label: string
  value: string | number
  sub?: string
  valueColor?: string
  sparkData?: number[]
  sparkPositive?: boolean
}

export function StatCard({ label, value, sub, valueColor, sparkData, sparkPositive = true }: StatCardProps) {
  const theme = useTheme()

  return (
    <div
      className="relative rounded-[14px] p-5 overflow-hidden"
      style={{
        backgroundColor: theme.colors.surface,
        border: `0.5px solid ${theme.colors.border}`,
        boxShadow: theme.isDark ? '0 2px 10px rgba(0,0,0,0.3)' : '0 2px 10px rgba(0,0,0,0.06)',
      }}
    >
      <p
        className="text-[11px] font-semibold uppercase tracking-wide mb-1"
        style={{ color: theme.colors.textSub }}
      >
        {label}
      </p>
      <p
        className="text-[28px] font-bold leading-tight"
        style={{ color: valueColor || theme.colors.text }}
      >
        {value}
      </p>
      {sub && (
        <p className="text-[11px] mt-1" style={{ color: theme.colors.textSub }}>
          {sub}
        </p>
      )}
      {sparkData && (
        <div className="absolute bottom-2 right-3 opacity-50">
          <SparkLine data={sparkData} positive={sparkPositive} width={56} height={24} />
        </div>
      )}
    </div>
  )
}
