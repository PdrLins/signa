'use client'

import { forwardRef } from 'react'
import { ExternalLink } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { Panel } from '@/components/insights/Panel'
import type { LongCheckResult } from '@/types/check'
import { LongVerdictCard } from './LongVerdictCard'
import { ScorecardGrid } from './ScorecardGrid'
import { ReturnsTable } from './ReturnsTable'
import { DrawdownCard } from './DrawdownCard'
import { FundPanel } from './FundPanel'
import { FundamentalsPanel } from './FundamentalsPanel'
import { longText } from './format'

/** Long-term hold result: verdict + AI assessment, scorecard, returns vs
 *  benchmark, drawdowns, fund or company data, red flags, caveats.
 *  Single column on phones; two columns from lg. */
export const LongResultView = forwardRef<HTMLHeadingElement, {
  result: LongCheckResult
  onRecheck: () => void
  recheckDisabled?: boolean
}>(function LongResultView({ result: r, onRecheck, recheckDisabled }, headingRef) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const tl = t.check.long

  return (
    <div className="flex flex-col gap-4 md:gap-6 min-w-0">
      <LongVerdictCard ref={headingRef} result={r} onRecheck={onRecheck} recheckDisabled={recheckDisabled} />

      <ScorecardGrid items={r.scorecard} />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 md:gap-6 items-start">
        <ReturnsTable result={r} />
        <DrawdownCard result={r} />
      </div>

      {r.fund && <FundPanel fund={r.fund} currency={r.currency} />}
      {r.fundamentals && <FundamentalsPanel data={r.fundamentals} currency={r.currency} />}

      {(r.asset_type === 'STOCK' || r.red_flags.length > 0) && (
        <Panel title={tl.redFlagsTitle}>
          {r.red_flags.length === 0 ? (
            <p className="text-[13px]" style={{ color: theme.colors.textSub }}>
              {r.ai.sentiment_called ? tl.redFlagsNone : tl.redFlagsNotSearched}
            </p>
          ) : (
            <ul className="flex flex-col gap-2">
              {r.red_flags.map((f, i) => (
                <li
                  key={i}
                  className="rounded-[10px] p-3 flex flex-col gap-1.5 min-w-0"
                  style={{ backgroundColor: theme.colors.surfaceAlt, borderLeft: `3px solid ${theme.colors.down}` }}
                >
                  <p className="text-[13px] break-words" style={{ color: theme.colors.text }}>{f.text}</p>
                  <div className="flex flex-wrap items-center gap-x-3 text-[12px]" style={{ color: theme.colors.textSub }}>
                    {(f.category || f.severity) && (
                      <span>
                        {[f.category?.replace(/_/g, ' '), f.severity ? (tl.severity as Record<string, string>)[f.severity] ?? f.severity : null]
                          .filter(Boolean).join(' · ')}
                      </span>
                    )}
                    {f.url && (
                      <a
                        href={f.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 min-h-11 font-medium hover:underline focus-visible:outline focus-visible:outline-2 rounded"
                        style={{ color: theme.colors.accent, outlineColor: theme.colors.primary }}
                      >
                        {tl.sourceLink}
                        <ExternalLink size={12} aria-hidden="true" />
                      </a>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      )}

      <Panel title={tl.caveatsTitle}>
        <ul className="flex flex-col gap-1.5">
          {r.caveats.map((c) => (
            <li key={c.code} className="text-[13px]" style={{ color: theme.colors.textSub }}>{longText(c, 'caveats', t)}</li>
          ))}
        </ul>
      </Panel>
    </div>
  )
})
