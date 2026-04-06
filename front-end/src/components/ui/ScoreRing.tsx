'use client'

import { useTheme } from '@/hooks/useTheme'

interface ScoreRingProps {
  score: number
  size?: number
}

export function ScoreRing({ score, size = 52 }: ScoreRingProps) {
  const theme = useTheme()

  const strokeWidth = 4
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius
  const offset = circumference - (score / 100) * circumference

  const color =
    score >= 80 ? theme.colors.up : score >= 60 ? theme.colors.warning : theme.colors.down

  return (
    <div className="relative inline-flex items-center justify-center" role="img" aria-label={`Score: ${score} out of 100`} style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={theme.colors.surfaceAlt}
          strokeWidth={strokeWidth}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
        />
      </svg>
      <span
        className="absolute text-xs font-bold"
        style={{ color, fontSize: size * 0.26 }}
      >
        {score}
      </span>
    </div>
  )
}
