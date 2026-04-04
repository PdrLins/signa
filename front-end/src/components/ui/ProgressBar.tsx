'use client'

import { useTheme } from '@/hooks/useTheme'

interface ProgressBarProps {
  value: number
  color?: string
  height?: number
}

export function ProgressBar({ value, color, height = 3 }: ProgressBarProps) {
  const theme = useTheme()
  const fillColor = color || theme.colors.primary

  return (
    <div
      className="w-full rounded-full overflow-hidden"
      style={{ height, backgroundColor: theme.colors.surfaceAlt }}
    >
      <div
        className="h-full rounded-full transition-all duration-500"
        style={{
          width: `${Math.min(100, Math.max(0, value))}%`,
          backgroundColor: fillColor,
        }}
      />
    </div>
  )
}
