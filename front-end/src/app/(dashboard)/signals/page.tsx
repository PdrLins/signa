'use client'

import { useState } from 'react'
import { useTheme } from '@/hooks/useTheme'
import { useAllSignals } from '@/hooks/useSignals'
import { SignalList } from '@/components/signals/SignalList'
import type { SignalFilters } from '@/types/signal'

export default function SignalsPage() {
  const theme = useTheme()
  const [bucket, setBucket] = useState<string>('All')
  const [minScore, setMinScore] = useState<number>(0)

  const filters: SignalFilters = {}
  if (bucket === 'SAFE_INCOME' || bucket === 'HIGH_RISK') filters.bucket = bucket
  if (minScore > 0) filters.min_score = minScore

  const { data: signals, isLoading, isError, error } = useAllSignals(
    Object.keys(filters).length ? filters : undefined
  )

  const bucketOptions = ['All', 'SAFE_INCOME', 'HIGH_RISK']
  const scoreOptions = [
    { label: 'Any score', value: 0 },
    { label: '60+', value: 60 },
    { label: '70+', value: 70 },
    { label: '80+', value: 80 },
  ]

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold" style={{ color: theme.colors.text }}>
          Signals
        </h1>
        {signals && (
          <p className="text-sm mt-1" style={{ color: theme.colors.textSub }}>
            Showing {signals.length} signals
          </p>
        )}
      </div>

      {/* Filter bar */}
      <div className="flex flex-wrap gap-3">
        {/* Bucket filter */}
        <div
          className="inline-flex items-center gap-1 rounded-xl px-1 py-1"
          style={{ backgroundColor: theme.colors.nav }}
        >
          {bucketOptions.map((opt) => {
            const isActive = bucket === opt
            return (
              <button
                key={opt}
                onClick={() => setBucket(opt)}
                className="px-2.5 py-1 rounded-lg text-[11px] font-medium transition-all"
                style={{
                  backgroundColor: isActive ? theme.colors.navActive : 'transparent',
                  color: isActive ? theme.colors.text : theme.colors.textSub,
                  boxShadow: isActive ? (theme.isDark ? '0 1px 3px rgba(0,0,0,0.3)' : '0 1px 3px rgba(0,0,0,0.08)') : 'none',
                }}
              >
                {opt === 'SAFE_INCOME' ? 'Safe Income' : opt === 'HIGH_RISK' ? 'High Risk' : opt}
              </button>
            )
          })}
        </div>

        {/* Min score filter */}
        <div
          className="inline-flex items-center gap-1 rounded-xl px-1 py-1"
          style={{ backgroundColor: theme.colors.nav }}
        >
          {scoreOptions.map((opt) => {
            const isActive = minScore === opt.value
            return (
              <button
                key={opt.value}
                onClick={() => setMinScore(opt.value)}
                className="px-2.5 py-1 rounded-lg text-[11px] font-medium transition-all"
                style={{
                  backgroundColor: isActive ? theme.colors.navActive : 'transparent',
                  color: isActive ? theme.colors.text : theme.colors.textSub,
                  boxShadow: isActive ? (theme.isDark ? '0 1px 3px rgba(0,0,0,0.3)' : '0 1px 3px rgba(0,0,0,0.08)') : 'none',
                }}
              >
                {opt.label}
              </button>
            )
          })}
        </div>
      </div>

      <SignalList signals={signals} isLoading={isLoading} isError={isError} error={error} />
    </div>
  )
}
