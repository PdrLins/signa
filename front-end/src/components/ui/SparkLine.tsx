'use client'

import { useTheme } from '@/hooks/useTheme'

const MOCK_UP = [4, 6, 5, 8, 7, 10, 9, 12, 11, 14]
const MOCK_DOWN = [14, 12, 13, 10, 11, 8, 9, 6, 7, 4]

interface SparkLineProps {
  positive?: boolean
  width?: number
  height?: number
  data?: number[]
}

export function SparkLine({ positive = true, width = 64, height = 28, data }: SparkLineProps) {
  const theme = useTheme()

  const points = data || (positive ? MOCK_UP : MOCK_DOWN)
  const color = positive ? theme.colors.up : theme.colors.down
  const id = `spark-${positive ? 'up' : 'down'}-${Math.random().toString(36).slice(2, 8)}`

  const max = Math.max(...points)
  const min = Math.min(...points)
  const range = max - min || 1

  const pathPoints = points
    .map((v, i) => {
      const x = (i / (points.length - 1)) * width
      const y = height - ((v - min) / range) * (height - 4) - 2
      return `${x},${y}`
    })
    .join(' ')

  const linePath = `M ${pathPoints.replace(/ /g, ' L ')}`
  const areaPath = `${linePath} L ${width},${height} L 0,${height} Z`

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.3" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={areaPath} fill={`url(#${id})`} />
      <path d={linePath} fill="none" stroke={color} strokeWidth="1.5" />
    </svg>
  )
}
