'use client'

import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { fill } from '@/lib/insights'
import type { Signal } from '@/types/signal'

/** Decision-first summary of a signal: filter result · AI verdict · Opus
 *  outcome · p_win. The score is shown small, last (display only). */
export function SignalVerdictChips({ signal, showScore = true }: { signal: Signal; showScore?: boolean }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const c = t.signalChips
  const stored = (signal.technical_data as Record<string, unknown> | null)?._tech_filter as { passed?: boolean } | undefined
  const tf = typeof signal.tech_filter_passed === 'boolean' ? { passed: signal.tech_filter_passed } : stored
  // Verdict fields are absent (undefined) when not loaded — show nothing
  // rather than a wrong "AI not called".
  const known = signal.ai_status !== undefined || signal.ai_signal !== undefined
  const aiCalled = !!signal.ai_signal || (signal.ai_status != null && signal.ai_status !== 'skipped')

  const chip = (text: string, color: string, key: string) => (
    <span
      key={key}
      className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold whitespace-nowrap"
      style={{ backgroundColor: color + '18', color }}
    >
      {text}
    </span>
  )

  const chips: React.ReactNode[] = []
  if (tf && typeof tf.passed === 'boolean') {
    chips.push(chip(tf.passed ? c.filterPassed : c.filterFailed, tf.passed ? theme.colors.up : theme.colors.textSub, 'tf'))
  }
  if (!known) {
    // nothing
  } else if (!aiCalled) {
    chips.push(chip(c.aiNotCalled, theme.colors.textSub, 'ai'))
  } else if (signal.ai_signal) {
    chips.push(chip(fill(c.aiVerdict, { signal: signal.ai_signal }), signal.ai_signal === 'BUY' ? theme.colors.up : theme.colors.warning, 'ai'))
  }
  if (signal.decision_overturned === false) chips.push(chip(c.opusConfirmed, theme.colors.up, 'opus'))
  if (signal.decision_overturned === true) chips.push(chip(c.opusVetoed, theme.colors.warning, 'opus'))
  if (signal.p_win != null) chips.push(chip(fill(c.pwin, { p: signal.p_win.toFixed(2) }), theme.colors.primary, 'pwin'))

  return (
    <div className="flex flex-wrap items-center gap-1.5" aria-label={c.verdictLabel}>
      {chips}
      {showScore && (
        <span className="text-[11px] tabular-nums" style={{ color: theme.colors.textSub }}>
          {fill(c.score, { s: signal.score })}
        </span>
      )}
    </div>
  )
}
