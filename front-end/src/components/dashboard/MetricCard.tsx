'use client'

import { useTheme } from '@/hooks/useTheme'

interface MetricCardProps {
  label: string
  value: string | number
  sub?: string
  valueColor?: string
  children?: React.ReactNode
}

export function MetricCard({ label, value, sub, valueColor, children }: MetricCardProps) {
  const theme = useTheme()

  return (
    <div
      className="rounded-[14px] p-4 overflow-hidden"
      style={{
        backgroundColor: theme.colors.surface,
        border: `0.5px solid ${theme.colors.border}`,
        boxShadow: theme.isDark ? '0 2px 10px rgba(0,0,0,0.3)' : '0 2px 10px rgba(0,0,0,0.06)',
      }}
    >
      {children ? (
        children
      ) : (
        <>
          <span
            className="text-[10px] font-semibold uppercase tracking-wide mb-1 block"
            style={{ color: theme.colors.textSub }}
          >
            {label}
          </span>
          <span
            className="text-[26px] font-bold leading-tight tabular-nums block"
            style={{ color: valueColor || theme.colors.text }}
          >
            {value}
          </span>
          {sub && (
            <span className="text-[11px] mt-0.5 block" style={{ color: theme.colors.textSub }}>
              {sub}
            </span>
          )}
        </>
      )}
    </div>
  )
}
