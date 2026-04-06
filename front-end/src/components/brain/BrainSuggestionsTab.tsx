'use client'

import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useToast } from '@/hooks/useToast'
import { useRunAnalysis, useApproveSuggestion, useRejectSuggestion, useApplySuggestion } from '@/hooks/useBrain'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'

interface BrainSuggestionsTabProps {
  suggestions: Record<string, unknown>[]
}

export function BrainSuggestionsTab({ suggestions }: BrainSuggestionsTabProps) {
  const theme = useTheme()
  const toast = useToast()
  const t = useI18nStore((s) => s.t)
  const runAnalysis = useRunAnalysis()
  const approveSuggestion = useApproveSuggestion()
  const rejectSuggestion = useRejectSuggestion()
  const applySuggestion = useApplySuggestion()

  return (
    <div role="tabpanel" id="tabpanel-suggestions" aria-labelledby="tab-suggestions" className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs" style={{ color: theme.colors.textSub }}>
          {t.brain.suggestionsDesc}
        </p>
        <Button
          onClick={() => {
            runAnalysis.mutate(7, {
              onSuccess: (data) => toast.show(`${data.count} ${t.brain.suggestionsGenerated}`, 'success'),
              onError: (err) => toast.show((err as Error)?.message || t.brain.analysisFailed, 'error'),
            })
          }}
          disabled={runAnalysis.isPending}
        >
          {runAnalysis.isPending ? t.brain.analyzing : t.brain.runAnalysis}
        </Button>
      </div>

      {suggestions.length === 0 ? (
        <p className="text-sm text-center py-8" style={{ color: theme.colors.textSub }}>
          {t.brain.noSuggestions}
        </p>
      ) : (
        suggestions.map((s) => {
          const isPending = s.status === 'PENDING'
          const isApproved = s.status === 'APPROVED'
          return (
            <div
              key={String(s.id)}
              className="rounded-xl px-4 py-3 space-y-2"
              style={{ backgroundColor: theme.colors.surfaceAlt, border: `1px solid ${theme.colors.border}` }}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold" style={{ color: theme.colors.text }}>
                    {String(s.rule_name)}
                  </span>
                  <Badge variant={isPending ? 'hold' : isApproved ? 'confirmed' : s.status === 'APPLIED' ? 'buy' : 'cancelled'}>
                    {String(s.status)}
                  </Badge>
                </div>
                <span className="text-[10px]" style={{ color: theme.colors.textHint }}>
                  {String(s.suggestion_type)}
                </span>
              </div>

              <p className="text-xs leading-relaxed" style={{ color: theme.colors.textSub }}>
                {String(s.reasoning)}
              </p>

              {Boolean(s.expected_impact) && (
                <p className="text-[10px]" style={{ color: theme.colors.primary }}>
                  {t.brain.expected}: {String(s.expected_impact)}
                </p>
              )}

              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-[10px]" style={{ color: theme.colors.textHint }}>
                    {t.brain.confidence}: {String(s.confidence)}%
                  </span>
                  <span className="text-[10px]" style={{ color: theme.colors.textHint }}>
                    {t.brain.winRate}: {s.win_rate ? `${(Number(s.win_rate) * 100).toFixed(0)}%` : '?'}
                  </span>
                </div>
                {isPending && (
                  <div className="flex items-center gap-1.5">
                    <button
                      onClick={() => rejectSuggestion.mutate({ id: String(s.id) }, {
                        onSuccess: () => toast.show(t.brain.suggestionRejected, 'info'),
                      })}
                      disabled={rejectSuggestion.isPending}
                      className="text-[10px] font-medium px-2 py-1 rounded-lg disabled:opacity-50"
                      style={{ backgroundColor: theme.colors.down + '15', color: theme.colors.down }}
                    >
                      {t.brain.reject}
                    </button>
                    <button
                      onClick={() => approveSuggestion.mutate(String(s.id), {
                        onSuccess: () => toast.show(t.brain.suggestionApproved, 'success'),
                      })}
                      disabled={approveSuggestion.isPending}
                      className="text-[10px] font-medium px-2 py-1 rounded-lg disabled:opacity-50"
                      style={{ backgroundColor: theme.colors.up + '15', color: theme.colors.up }}
                    >
                      {t.brain.approve}
                    </button>
                  </div>
                )}
                {isApproved && (
                  <button
                    onClick={() => applySuggestion.mutate(String(s.id), {
                      onSuccess: () => toast.show(t.brain.appliedSuccess, 'success'),
                      onError: (err) => toast.show((err as Error)?.message || t.brain.appliedFailed, 'error'),
                    })}
                    disabled={applySuggestion.isPending}
                    className="text-[10px] font-bold px-3 py-1 rounded-lg disabled:opacity-50"
                    style={{ backgroundColor: theme.colors.primary + '15', color: theme.colors.primary }}
                  >
                    {t.brain.applyToBrain}
                  </button>
                )}
              </div>
            </div>
          )
        })
      )}
    </div>
  )
}
