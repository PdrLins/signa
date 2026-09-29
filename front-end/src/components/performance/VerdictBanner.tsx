'use client'

import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { fill, signedFracPct } from '@/lib/insights'
import type { PerformanceInsights } from '@/types/insights'

export function VerdictBanner({ data }: { data: PerformanceInsights }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const v = t.performance.verdict
  const { state, n, needed, mean, ci } = data.verdict
  const color = state === 'positive' ? theme.colors.up : state === 'negative' ? theme.colors.down : theme.colors.warning
  const frac = Math.min(1, needed > 0 ? n / needed : 0)
  const title = state === 'insufficient' ? v.insufficient : state === 'positive' ? v.positive : state === 'negative' ? v.negative : v.inconclusive
  const vars = { n, needed, h: data.horizon, mean: signedFracPct(mean), lo: signedFracPct(ci?.[0]), hi: signedFracPct(ci?.[1]) }
  const body = state === 'insufficient' ? fill(v.insufficientBody, vars) : state === 'inconclusive' ? fill(v.inconclusiveBody, vars) : fill(v.decidedBody, vars)
  // ring: conic progress towards the n threshold
  const ring = `conic-gradient(${color} ${frac * 360}deg, ${theme.colors.surfaceAlt} 0deg)`

  const stat = (label: string, value: string) => (
    <div className="flex flex-col gap-0.5">
      <span className="text-[12px]" style={{ color: theme.colors.textSub }}>{label}</span>
      <span className="text-[18px] md:text-[20px] tabular-nums" style={{ color: theme.colors.text, fontFamily: 'var(--font-mono)' }}>{value}</span>
    </div>
  )

  return (
    <section
      aria-labelledby="verdict-h"
      className="rounded-2xl p-5 md:px-6 flex flex-col md:flex-row gap-4 md:gap-5 md:items-center"
      style={{ backgroundColor: theme.colors.surface, border: `1px solid ${color}4D` }}
    >
      <div className="flex items-center gap-4 md:gap-5 flex-1 min-w-0">
        <div
          className="w-[52px] h-[52px] rounded-full shrink-0 grid place-items-center"
          style={{ background: ring }}
          role="progressbar"
          aria-valuenow={n}
          aria-valuemin={0}
          aria-valuemax={needed}
          aria-label={fill(v.progress, { n, needed })}
        >
          <span className="w-[42px] h-[42px] rounded-full grid place-items-center text-[11px] tabular-nums" style={{ backgroundColor: theme.colors.surface, color: theme.colors.text, fontFamily: 'var(--font-mono)' }}>
            {n}/{needed}
          </span>
        </div>
        <div className="flex flex-col gap-1 min-w-0">
          <h2 id="verdict-h" className="text-[18px] font-semibold" style={{ color: theme.colors.text }}>{title}</h2>
          <p className="text-sm" style={{ color: theme.colors.text }}>{body}</p>
        </div>
      </div>
      <div className="flex gap-6 md:gap-7 flex-wrap">
        {stat(v.tracked, String(data.counts.tracked))}
        {stat(v.validated, `${data.counts.validated_buys} / ${needed}`)}
        {stat(v.closed, `${data.counts.closed_trades} / ${needed}`)}
      </div>
    </section>
  )
}
