'use client'

import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { ProgressBar } from '@/components/ui/ProgressBar'
import type { ScanProgress } from '@/lib/api'

/** Live progress of a manually triggered scan (see useScanTrigger). */
export function ScanProgressPanel({ progress, phaseLabel }: {
  progress: ScanProgress
  phaseLabel: (phase: string) => string
}) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  return (
    <div
      className="rounded-xl px-4 py-3 space-y-2"
      style={{ backgroundColor: theme.colors.surfaceAlt, border: `1px solid ${theme.colors.border}` }}
      role="status"
      aria-live="polite"
    >
      <div className="flex justify-between items-center">
        <span className="text-xs font-medium" style={{ color: theme.colors.text }}>
          {phaseLabel(progress.phase)}
        </span>
        <span className="text-xs tabular-nums font-semibold" style={{ color: theme.colors.primary }}>
          {progress.progress_pct}%
        </span>
      </div>
      <ProgressBar value={progress.progress_pct} color={theme.colors.primary} height={4} />
      {progress.signals_found > 0 && (
        <p className="text-[11px]" style={{ color: theme.colors.textSub }}>
          {progress.gems_found > 0
            ? t.signals.signalsFoundGems.replace('{count}', String(progress.signals_found)).replace('{gems}', String(progress.gems_found))
            : t.signals.signalsFound.replace('{count}', String(progress.signals_found))}
        </p>
      )}
    </div>
  )
}
