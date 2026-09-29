'use client'

import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { Panel } from '@/components/insights/Panel'
import { signedPct, shortDate } from '@/lib/insights'
import type { PerformanceInsights } from '@/types/insights'

export function EquityChart({ curve }: { curve: PerformanceInsights['equity_curve'] }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const e = t.performance.equity
  const points = curve.points
  const series = [
    { key: 'signa', label: e.signa, color: theme.colors.up, width: 2.5, dash: undefined, total: curve.signa_pct },
    { key: 'spy', label: e.spy, color: theme.colors.textSub, width: 2, dash: undefined, total: curve.spy_pct },
    { key: 'xiu', label: e.xiu, color: theme.colors.warning, width: 2, dash: '6 5', total: curve.xiu_pct },
  ].filter((s) => points.some((p) => p[s.key as 'signa' | 'spy' | 'xiu'] != null))

  return (
    <Panel
      title={e.title}
      right={
        series.length > 0 ? (
          <ul className="flex flex-wrap gap-x-4 gap-y-1 text-[13px]" style={{ color: theme.colors.text }}>
            {series.map((s) => (
              <li key={s.key} className="flex items-center gap-1.5">
                <svg width="16" height="4" aria-hidden="true"><line x1="0" y1="2" x2="16" y2="2" stroke={s.color} strokeWidth="3" strokeDasharray={s.dash ? '4 3' : undefined} /></svg>
                {s.label} <span className="tabular-nums" style={{ fontFamily: 'var(--font-mono)' }}>{signedPct(s.total)}</span>
              </li>
            ))}
          </ul>
        ) : undefined
      }
    >
      {points.length < 2 || series.length === 0 ? (
        <p className="text-sm py-6" style={{ color: theme.colors.textSub }}>{e.empty}</p>
      ) : (
        <div className="h-[220px]" role="img" aria-label={e.chartLabel}>
          <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={0}>
            <LineChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid vertical={false} stroke={theme.colors.border} />
              <XAxis
                dataKey="date"
                tickFormatter={(d: string) => shortDate(d, locale)}
                tick={{ fontSize: 11, fill: theme.colors.textSub }}
                axisLine={false}
                tickLine={false}
                minTickGap={48}
              />
              <YAxis
                tickFormatter={(v: number) => `${v.toFixed(0)}%`}
                tick={{ fontSize: 11, fill: theme.colors.textSub }}
                axisLine={false}
                tickLine={false}
                width={44}
              />
              <Tooltip
                contentStyle={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.border}`, borderRadius: 8, fontSize: 12, color: theme.colors.text }}
                labelFormatter={(d) => shortDate(String(d), locale, true)}
                formatter={(v, name) => [signedPct(v == null ? null : Number(v)), series.find((s) => s.key === name)?.label ?? String(name)]}
              />
              {series.map((s) => (
                <Line
                  key={s.key}
                  type="monotone"
                  dataKey={s.key}
                  stroke={s.color}
                  strokeWidth={s.width}
                  strokeDasharray={s.dash}
                  dot={false}
                  connectNulls
                  isAnimationActive={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </Panel>
  )
}
