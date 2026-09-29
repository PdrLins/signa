'use client'

import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { Panel } from '@/components/insights/Panel'
import { fill, etTime, DASH } from '@/lib/insights'
import type { ScanFunnel as Funnel, ScanRef, RiskLimits } from '@/types/insights'

interface Step {
  key: string
  n: number | null
  label: string
  sub: string
}

/** Log-scaled share of the largest step, so 1 of 281 is still visible. */
function share(n: number | null, max: number): number {
  if (n == null || max <= 0) return 0
  return Math.max(0.06, Math.log(n + 1) / Math.log(max + 1))
}

export function ScanFunnel({ funnel, scan, limits }: { funnel: Funnel; scan: ScanRef | null; limits: RiskLimits }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const f = t.today.funnel
  const vetoed = Math.max(0, funnel.routine_buy - funnel.decision_confirmed)

  const steps: Step[] = [
    { key: 'universe', n: funnel.universe, label: f.universe, sub: f.universeSub },
    { key: 'candidates', n: funnel.candidates, label: f.candidates, sub: f.candidatesSub },
    { key: 'passed', n: funnel.passed_filter, label: f.passedFilter, sub: funnel.passed_filter == null ? f.notRecorded : f.passedFilterSub },
    { key: 'ai', n: funnel.ai_checked, label: f.aiChecked, sub: f.aiCheckedSub },
    { key: 'routine', n: funnel.routine_buy, label: f.routineBuy, sub: fill(f.routineBuySub, { min: 60 }) },
    { key: 'confirmed', n: funnel.decision_confirmed, label: f.confirmed, sub: fill(f.confirmedSub, { n: vetoed }) },
    { key: 'bought', n: funnel.bought, label: f.bought, sub: fill(f.boughtSub, { risk: limits.risk_per_trade_pct }) },
  ]
  const max = Math.max(...steps.map((s) => s.n ?? 0), 1)
  // Bars step from a faint to the full accent colour; the last step (bought) uses `up`.
  const alphas = ['33', '4D', '66', '80', 'A6', 'CC', '']
  const color = (i: number) => (i === steps.length - 1 ? theme.colors.up : theme.colors.primary + alphas[i])

  return (
    <Panel
      title={fill(f.title, { time: etTime(scan?.completed_at ?? scan?.started_at, locale) })}
      right={
        funnel.universe != null ? (
          <span className="hidden md:inline text-[13px]" style={{ color: theme.colors.textSub }}>
            {fill(f.subtitle, { universe: funnel.universe, bought: funnel.bought })}
          </span>
        ) : undefined
      }
    >
      {/* Desktop: vertical bars */}
      <ol className="hidden md:grid grid-cols-7 gap-2.5 items-end">
        {steps.map((s, i) => (
          <li key={s.key} className="flex flex-col gap-2 min-w-0">
            <span className="text-[22px] font-medium tabular-nums" style={{ color: theme.colors.text, fontFamily: 'var(--font-mono)' }}>
              {s.n ?? DASH}
            </span>
            <div className="h-16 flex items-end" aria-hidden="true">
              <div
                className="w-full"
                style={{ height: `${Math.round(share(s.n, max) * 64)}px`, backgroundColor: color(i), borderRadius: '6px 6px 2px 2px' }}
              />
            </div>
            <span className="text-[13px] font-medium" style={{ color: theme.colors.text }}>{s.label}</span>
            <span className="text-[12px] leading-snug" style={{ color: theme.colors.textSub }}>{s.sub}</span>
          </li>
        ))}
      </ol>
      {/* Mobile: horizontal bars */}
      <ol className="md:hidden flex flex-col gap-2.5">
        {steps.map((s, i) => (
          <li key={s.key} className="grid grid-cols-[110px_minmax(0,1fr)_40px] gap-2.5 items-center">
            <span className="text-[13px]" style={{ color: theme.colors.text }}>{s.label}</span>
            <div className="h-2 rounded" style={{ backgroundColor: theme.colors.surfaceAlt }} aria-hidden="true">
              <div className="h-2 rounded" style={{ width: `${share(s.n, max) * 100}%`, backgroundColor: color(i) }} />
            </div>
            <span className="text-[13px] text-right tabular-nums" style={{ color: theme.colors.text, fontFamily: 'var(--font-mono)' }}>
              {s.n ?? DASH}
            </span>
          </li>
        ))}
      </ol>
    </Panel>
  )
}
