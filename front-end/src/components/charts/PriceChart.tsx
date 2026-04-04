'use client'

import { useState } from 'react'
import dynamic from 'next/dynamic'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { usePriceHistory } from '@/hooks/usePriceHistory'
import { Skeleton } from '@/components/ui/Skeleton'
import type { TimeRange } from '@/types/chart'

const AreaChart = dynamic(() => import('recharts').then((m) => m.AreaChart), { ssr: false })
const Area = dynamic(() => import('recharts').then((m) => m.Area), { ssr: false })
const XAxis = dynamic(() => import('recharts').then((m) => m.XAxis), { ssr: false })
const YAxis = dynamic(() => import('recharts').then((m) => m.YAxis), { ssr: false })
const Tooltip = dynamic(() => import('recharts').then((m) => m.Tooltip), { ssr: false })
const ResponsiveContainer = dynamic(() => import('recharts').then((m) => m.ResponsiveContainer), { ssr: false })

interface PriceChartProps {
  symbol: string
  basePrice?: number
}

const TIME_RANGES: TimeRange[] = ['1D', '1W', '1M', '3M']

export function PriceChart({ symbol, basePrice }: PriceChartProps) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const [range, setRange] = useState<TimeRange>('1M')
  const { data: points, isLoading } = usePriceHistory(symbol, range, basePrice ?? undefined)

  if (isLoading) {
    return <Skeleton width="100%" height={200} borderRadius={9} />
  }

  if (!points?.length) {
    return (
      <div className="text-center py-6">
        <p className="text-xs" style={{ color: theme.colors.textSub }}>{t.charts.noData}</p>
      </div>
    )
  }

  const prices = points.map((p) => p.price)
  const minPrice = Math.min(...prices)
  const maxPrice = Math.max(...prices)
  const isPositive = prices[prices.length - 1] >= prices[0]
  const lineColor = isPositive ? theme.colors.up : theme.colors.down

  const formatDate = (iso: string) => {
    const d = new Date(iso)
    if (range === '1D') return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: 'America/Toronto' })
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'America/Toronto' })
  }

  return (
    <div>
      {/* Time range pills */}
      <div className="flex items-center justify-between mb-3">
        <p className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: theme.colors.textSub }}>
          {t.charts.priceChart}
        </p>
        <div
          className="inline-flex items-center gap-0.5 rounded-lg px-0.5 py-0.5"
          style={{ backgroundColor: theme.colors.surfaceAlt }}
        >
          {TIME_RANGES.map((r) => (
            <button
              key={r}
              onClick={(e) => { e.stopPropagation(); setRange(r) }}
              className="px-2 py-0.5 rounded-md text-[10px] font-semibold transition-all"
              style={{
                backgroundColor: range === r ? theme.colors.surface : 'transparent',
                color: range === r ? theme.colors.text : theme.colors.textSub,
                boxShadow: range === r ? (theme.isDark ? '0 1px 2px rgba(0,0,0,0.3)' : '0 1px 2px rgba(0,0,0,0.08)') : 'none',
              }}
            >
              {t.charts[r]}
            </button>
          ))}
        </div>
      </div>

      {/* Chart */}
      <div style={{ height: 200 }}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={points} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id={`grad-${symbol}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={lineColor} stopOpacity={0.2} />
                <stop offset="100%" stopColor={lineColor} stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis
              dataKey="date"
              tickFormatter={formatDate}
              tick={{ fontSize: 10, fill: theme.colors.textHint }}
              axisLine={false}
              tickLine={false}
              interval="preserveStartEnd"
              minTickGap={40}
            />
            <YAxis
              domain={[minPrice * 0.998, maxPrice * 1.002]}
              tick={{ fontSize: 10, fill: theme.colors.textHint }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(v: number) => `$${v.toFixed(0)}`}
              width={40}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: theme.colors.surface,
                border: `1px solid ${theme.colors.border}`,
                borderRadius: 8,
                fontSize: 12,
                color: theme.colors.text,
                boxShadow: theme.isDark ? '0 4px 12px rgba(0,0,0,0.4)' : '0 4px 12px rgba(0,0,0,0.1)',
              }}
              labelFormatter={(label) => formatDate(String(label))}
              formatter={(value) => [`$${Number(value).toFixed(2)}`, 'Price']}
            />
            <Area
              type="monotone"
              dataKey="price"
              stroke={lineColor}
              strokeWidth={2}
              fill={`url(#grad-${symbol})`}
              dot={false}
              activeDot={{ r: 4, fill: lineColor, stroke: theme.colors.surface, strokeWidth: 2 }}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
