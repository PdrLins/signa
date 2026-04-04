'use client'

import { SignalCard, SignalCardSkeleton } from './SignalCard'
import { useTheme } from '@/hooks/useTheme'
import type { Signal } from '@/types/signal'

interface SignalListProps {
  signals: Signal[] | undefined
  isLoading: boolean
  isError: boolean
  error?: Error | null
}

export function SignalList({ signals, isLoading, isError, error }: SignalListProps) {
  const theme = useTheme()

  if (isLoading) {
    return (
      <div className="space-y-3">
        <SignalCardSkeleton />
        <SignalCardSkeleton />
      </div>
    )
  }

  if (isError) {
    return (
      <div className="text-center py-8">
        <p className="text-sm" style={{ color: theme.colors.down }}>
          {error?.message || 'Failed to load signals'}
        </p>
      </div>
    )
  }

  if (!signals?.length) {
    return (
      <div className="text-center py-12">
        <p className="text-lg font-semibold mb-1" style={{ color: theme.colors.text }}>
          No signals yet
        </p>
        <p className="text-sm" style={{ color: theme.colors.textSub }}>
          Signals will appear here after the next scan completes.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {signals.map((signal) => (
        <SignalCard key={signal.id} signal={signal} />
      ))}
    </div>
  )
}
