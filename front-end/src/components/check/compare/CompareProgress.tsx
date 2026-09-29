'use client'

import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { ProgressBar } from '@/components/ui/ProgressBar'
import { Panel } from '@/components/insights/Panel'
import { fill } from '@/lib/insights'
import type { CheckMode, CompareItem, CompareJob } from '@/types/check'

/** Per-symbol progress rows; a polite live region announces status changes
 *  (not every percent tick). */
export function CompareProgress({ job, tickers, mode }: { job: CompareJob | null; tickers: string[]; mode: CheckMode }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const tc = t.check
  const phaseNames = (mode === 'long' ? tc.longPhases : tc.phases) as Record<string, string>
  const items: CompareItem[] = job?.items ?? tickers.map((s) => ({
    input: s, symbol: s, status: 'running', phase: 'resolving', pct: 0, cached: null, error: null,
  }))
  const pct = job?.pct ?? 0
  const summarizing = job?.phase === 'summarizing'
  const title = fill(tc.compare.progressTitle, { symbols: items.map((i) => i.symbol).join(' · ') })

  const statusText = (it: CompareItem) => {
    if (it.status === 'failed') return tc.compare.status.failed
    if (it.status === 'queued') return tc.compare.status.queued
    if (it.status === 'done') return it.cached ? `${tc.compare.status.done} · ${tc.compare.cachedBadge}` : tc.compare.status.done
    return phaseNames[it.phase] ?? tc.compare.status.running
  }

  return (
    <Panel title={title}>
      <div className="flex flex-col gap-4">
        <p className="sr-only" role="status" aria-live="polite">
          {items.map((it) => `${it.symbol}: ${statusText(it)}`).join('; ')}
          {summarizing ? `; ${tc.compare.summarizing}` : ''}
        </p>
        <div
          role="progressbar"
          aria-label={tc.compare.progressLabel}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={pct}
          aria-valuetext={`${pct}%${summarizing ? ` · ${tc.compare.summarizing}` : ''}`}
        >
          <ProgressBar value={pct} height={6} />
        </div>
        <ul className="flex flex-col gap-3">
          {items.map((it) => (
            <li key={it.symbol} className="flex flex-col gap-1.5 min-w-0">
              <div className="flex items-baseline justify-between gap-3 min-w-0">
                <span className="text-[14px] font-semibold shrink-0" style={{ color: theme.colors.text, fontFamily: 'var(--font-mono)' }}>
                  {it.symbol}
                </span>
                <span
                  className="text-[12px] truncate"
                  style={{ color: it.status === 'failed' ? theme.colors.down : it.status === 'done' ? theme.colors.up : theme.colors.textSub }}
                >
                  {statusText(it)}{it.status === 'running' ? ` · ${it.pct}%` : ''}
                </span>
              </div>
              <div
                role="progressbar"
                aria-label={it.symbol}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={it.pct}
                aria-valuetext={`${it.pct}% · ${statusText(it)}`}
              >
                <ProgressBar value={it.pct} height={4} />
              </div>
              {it.status === 'failed' && it.error && (
                <p className="text-[12px]" style={{ color: theme.colors.textSub }}>
                  {(tc.errors as Record<string, string>)[it.error.code]
                    ? fill((tc.errors as Record<string, string>)[it.error.code], { ticker: it.symbol })
                    : it.error.message}
                </p>
              )}
            </li>
          ))}
        </ul>
        {summarizing && <p className="text-[13px]" style={{ color: theme.colors.text }}>{tc.compare.summarizing}…</p>}
      </div>
    </Panel>
  )
}
