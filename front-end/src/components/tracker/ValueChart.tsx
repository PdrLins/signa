'use client'

// Portfolio value line (recharts). Import through next/dynamic with ssr:false.
import { memo, useMemo } from 'react'
import { Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useTheme } from '@/hooks/useTheme'
import type { SeriesPoint } from '@/types/tracker'

export interface ValueChartProps {
  series: SeriesPoint[]
  compare?: SeriesPoint[] | null
  /** dotted baseline (the range's first value / previous close) */
  baseline: number | null
  color: string
  height: number
  formatValue: (v: number) => string
  formatTime: (t: string) => string
  seriesLabel: string
  compareLabel?: string
  /** vertical dotted lines at these ISO times (1D: market open / close) */
  marks?: string[]
}

interface Row {
  t: string
  v: number | null
  c: number | null
}

function ValueChart({ series, compare, baseline, color, height, formatValue, formatTime, seriesLabel, compareLabel, marks }: ValueChartProps) {
  const theme = useTheme()
  const rows = useMemo<Row[]>(() => {
    const byT = new Map<string, Row>()
    for (const p of series) byT.set(p.t, { t: p.t, v: p.value, c: null })
    for (const p of compare ?? []) {
      const r = byT.get(p.t)
      if (r) r.c = p.value
      else byT.set(p.t, { t: p.t, v: null, c: p.value })
    }
    return Array.from(byT.values()).sort((a, b) => (a.t < b.t ? -1 : a.t > b.t ? 1 : 0))
  }, [series, compare])
  // a mark sits on the first point at/after its time, only when points exist on both sides
  const markTs = useMemo(() => (marks ?? []).map((m) => {
    const ms = Date.parse(m)
    if (!rows.length || Date.parse(rows[0].t) >= ms) return null
    return rows.find((r) => Date.parse(r.t) >= ms)?.t ?? null
  }).filter((x): x is string => !!x), [marks, rows])

  return (
    <div style={{ height }} className="w-full min-w-0">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={rows} margin={{ top: 8, right: 4, bottom: 0, left: 4 }}>
          <XAxis dataKey="t" hide />
          <YAxis hide domain={['auto', 'auto']} />
          {baseline !== null && (
            <ReferenceLine y={baseline} stroke={theme.colors.textSub} strokeDasharray="2 4" strokeWidth={1} ifOverflow="extendDomain" />
          )}
          {markTs.map((t) => (
            <ReferenceLine key={t} x={t} stroke={theme.colors.textHint} strokeDasharray="2 3" strokeWidth={1} />
          ))}
          <Tooltip
            cursor={{ stroke: theme.colors.border, strokeWidth: 1 }}
            content={({ active, payload, label }) => {
              if (!active || !payload?.length) return null
              const row = payload[0]?.payload as Row | undefined
              if (!row) return null
              return (
                <div className="rounded-lg px-2.5 py-1.5 text-[12px] tabular-nums"
                  style={{ backgroundColor: theme.colors.surfaceAlt, border: `1px solid ${theme.colors.border}`, color: theme.colors.text }}>
                  <div style={{ color: theme.colors.textSub }}>{formatTime(String(label))}</div>
                  {row.v !== null && <div>{seriesLabel}: {formatValue(row.v)}</div>}
                  {row.c !== null && compareLabel && <div style={{ color: theme.colors.textSub }}>{compareLabel}: {formatValue(row.c)}</div>}
                </div>
              )
            }}
          />
          {compare && compare.length > 0 && (
            <Line type="monotone" dataKey="c" stroke={theme.colors.textSub} strokeWidth={1.5} strokeDasharray="5 4"
              dot={false} connectNulls isAnimationActive={false} />
          )}
          <Line type="monotone" dataKey="v" stroke={color} strokeWidth={2} dot={false} connectNulls isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

export default memo(ValueChart)
