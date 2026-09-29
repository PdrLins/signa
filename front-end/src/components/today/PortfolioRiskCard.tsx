'use client'

import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { Panel } from '@/components/insights/Panel'
import { fill, num, DASH } from '@/lib/insights'
import type { PortfolioRisk, RiskLimits } from '@/types/insights'

export function PortfolioRiskCard({ risk, limits }: { risk: PortfolioRisk | null; limits: RiskLimits }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const r = t.today.risk
  const has = risk && risk.n_positions > 0 && (risk.beta != null || risk.vol_annual_pct != null || risk.max_pair)

  const tile = (label: string, value: string) => (
    <div className="flex flex-col gap-1 min-w-0">
      <span className="text-[12px]" style={{ color: theme.colors.textSub }}>{label}</span>
      <span className="text-[18px] tabular-nums" style={{ color: theme.colors.text, fontFamily: 'var(--font-mono)' }}>{value}</span>
    </div>
  )

  return (
    <Panel title={r.title}>
      {has && risk ? (
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-3 gap-2.5">
            {tile(r.beta, num(risk.beta))}
            {tile(r.vol, risk.vol_annual_pct != null ? `${risk.vol_annual_pct.toFixed(1)}%` : DASH)}
            {tile(r.maxCorr, risk.max_pair ? num(risk.max_pair.corr) : DASH)}
          </div>
          <p className="text-[12px] leading-relaxed" style={{ color: theme.colors.textSub }}>
            {risk.max_pair && <>{fill(r.cluster, { a: risk.max_pair.a, b: risk.max_pair.b, corr: num(risk.max_pair.corr) })} </>}
            {fill(r.rule, { pair: limits.corr_max_pairwise.toFixed(2), cluster: limits.corr_cluster_threshold.toFixed(2) })}
          </p>
        </div>
      ) : (
        <p className="text-sm" style={{ color: theme.colors.textSub }}>{r.unavailable}</p>
      )}
    </Panel>
  )
}
