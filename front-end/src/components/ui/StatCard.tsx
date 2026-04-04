'use client'

import { useTheme } from '@/hooks/useTheme'

interface StatCardProps {
  label: string
  value: string | number
  sub?: string
  valueColor?: string
}

export function StatCard({ label, value, sub, valueColor }: StatCardProps) {
  const theme = useTheme()

  return (
    <div
      className="rounded-[14px] p-4"
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
        className="text-[22px] font-bold leading-tight"
        style={{ color: valueColor || theme.colors.text }}
      >
        {value}
      </p>
      {sub && (
        <p className="text-[11px] mt-0.5" style={{ color: theme.colors.textSub }}>
          {sub}
        </p>
      )}
    </div>
  )
}
