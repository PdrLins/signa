'use client'

import dynamic from 'next/dynamic'
import { useTheme } from '@/hooks/useTheme'

// react-d3-speedometer uses D3 DOM manipulation — must be client-only
const ReactSpeedometer = dynamic(() => import('react-d3-speedometer'), {
  ssr: false,
  loading: () => <div style={{ width: 140, height: 90 }} />,
})

interface FearGreedGaugeProps {
  score: number | null
  label: string | null
}

export function FearGreedGauge({ score, label }: FearGreedGaugeProps) {
  const theme = useTheme()
  const value = score ?? 50

  return (
    <div className="flex flex-col items-center justify-center -mb-2">
      <ReactSpeedometer
        value={value}
        minValue={0}
        maxValue={100}
        segments={5}
        segmentColors={[
          theme.colors.down,      // 0-20: Extreme Fear
          '#F97316',              // 20-40: Fear (orange)
          theme.colors.warning,   // 40-60: Neutral
          '#84CC16',              // 60-80: Greed (lime)
          theme.colors.up,        // 80-100: Extreme Greed
        ]}
        customSegmentStops={[0, 20, 40, 60, 80, 100]}
        needleColor={theme.colors.text}
        needleTransitionDuration={800}
        needleHeightRatio={0.7}
        currentValueText=""
        width={140}
        height={90}
        ringWidth={14}
        textColor="transparent"
        labelFontSize="0"
        valueTextFontSize="0"
      />
      <span
        className="text-[20px] font-bold leading-none tabular-nums -mt-4 block text-center"
        style={{
          color: score == null ? theme.colors.textSub
            : score <= 25 ? theme.colors.down
            : score <= 45 ? '#F97316'
            : score >= 75 ? theme.colors.up
            : score >= 55 ? '#84CC16'
            : theme.colors.warning,
        }}
      >
        {score == null ? '\u2014' : score.toFixed(0)}
      </span>
      <span className="text-[10px] block text-center" style={{ color: theme.colors.textSub }}>
        {label ?? 'Fear & Greed'}
      </span>
    </div>
  )
}
