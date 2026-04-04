'use client'

import { useTheme } from '@/hooks/useTheme'

interface SkeletonProps {
  width?: string | number
  height?: string | number
  borderRadius?: string | number
  className?: string
}

export function Skeleton({ width, height, borderRadius = 8, className }: SkeletonProps) {
  const theme = useTheme()
  const shimmerColor = theme.isDark ? '#2A2A2A' : '#E5E5EA'
  const shimmerHighlight = theme.isDark ? '#3A3A3A' : '#F2F2F7'

  return (
    <div
      className={className}
      style={{
        width,
        height,
        borderRadius,
        background: `linear-gradient(90deg, ${shimmerColor} 25%, ${shimmerHighlight} 50%, ${shimmerColor} 75%)`,
        backgroundSize: '200% 100%',
        animation: 'shimmer 1.5s ease-in-out infinite',
      }}
    />
  )
}
