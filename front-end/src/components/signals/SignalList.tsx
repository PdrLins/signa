'use client'

import { SignalCard, SignalCardSkeleton } from './SignalCard'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import type { Signal } from '@/types/signal'

interface SignalListProps {
  signals: Signal[] | undefined
  isLoading: boolean
  isError: boolean
  error?: Error | null
  emptyMessage?: string
  topPickId?: string
}

export function SignalList({ signals, isLoading, isError, error, emptyMessage, topPickId }: SignalListProps) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)

  if (isLoading) {
    return (
      <div className="space-y-4">
        <SignalCardSkeleton />
        <SignalCardSkeleton />
      </div>
    )
  }

  if (isError) {
    return (
      <div className="text-center py-8">
        <p className="text-sm" style={{ color: theme.colors.down }}>
          {error?.message || t.signals.loadFailed}
        </p>
      </div>
    )
  }

  if (!signals?.length) {
    return (
      <div className="text-center py-12">
        <p className="text-lg font-semibold mb-1" style={{ color: theme.colors.text }}>
          {t.signals.noSignals}
        </p>
        <p className="text-sm" style={{ color: theme.colors.textSub }}>
          {emptyMessage || t.signals.noSignalsDesc}
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {signals.map((signal) => (
        <SignalCard key={signal.id} signal={signal} isTopPick={signal.id === topPickId} />
      ))}
    </div>
  )
}
