'use client'

import { useState } from 'react'
import { useTheme } from '@/hooks/useTheme'
import { useGemSignals } from '@/hooks/useSignals'
import { StatsBar } from '@/components/dashboard/StatsBar'
import { SignalList } from '@/components/signals/SignalList'
import { WatchlistTable } from '@/components/watchlist/WatchlistTable'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import type { Signal } from '@/types/signal'

type BucketFilter = 'ALL' | 'HIGH_RISK' | 'SAFE_INCOME'

function getGreeting(): string {
  const hour = new Date().getHours()
  if (hour < 12) return 'Good morning'
  if (hour < 18) return 'Good afternoon'
  return 'Good evening'
}

export default function OverviewPage() {
  const theme = useTheme()
  const { data: gems, isLoading, isError, error } = useGemSignals()
  const [filter, setFilter] = useState<BucketFilter>('ALL')

  const filtered = gems?.filter((s: Signal) => {
    if (filter === 'ALL') return true
    return s.bucket === filter
  })

  const filters: { label: string; value: BucketFilter }[] = [
    { label: 'All', value: 'ALL' },
    { label: 'High Risk', value: 'HIGH_RISK' },
    { label: 'Safe Income', value: 'SAFE_INCOME' },
  ]

  return (
    <div className="space-y-6">
      {/* Greeting */}
      <div>
        <h1 className="text-2xl font-bold" style={{ color: theme.colors.text }}>
          {getGreeting()}
        </h1>
        <p className="text-sm mt-1" style={{ color: theme.colors.textSub }}>
          Here&apos;s your market overview for today.
        </p>
      </div>

      {/* Stats */}
      <StatsBar />

      {/* Gems section */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-bold" style={{ color: theme.colors.text }}>
              Top signals
            </h2>
            {gems && <Badge variant="gem">{gems.length}</Badge>}
          </div>
        </div>

        {/* Filter tabs */}
        <div
          className="inline-flex items-center gap-1 rounded-xl px-1 py-1 mb-4"
          style={{ backgroundColor: theme.colors.nav }}
        >
          {filters.map((f) => (
            <button
              key={f.value}
              onClick={() => setFilter(f.value)}
              className="px-3 py-1 rounded-lg text-xs font-medium transition-all"
              style={{
                backgroundColor: filter === f.value ? theme.colors.navActive : 'transparent',
                color: filter === f.value ? theme.colors.text : theme.colors.textSub,
                boxShadow: filter === f.value ? (theme.isDark ? '0 1px 3px rgba(0,0,0,0.3)' : '0 1px 3px rgba(0,0,0,0.08)') : 'none',
              }}
            >
              {f.label}
            </button>
          ))}
        </div>

        <SignalList
          signals={filtered}
          isLoading={isLoading}
          isError={isError}
          error={error}
        />
      </div>

      {/* Watchlist */}
      <Card padding="16px">
        <h2 className="text-base font-bold mb-3" style={{ color: theme.colors.text }}>
          Watchlist
        </h2>
        <WatchlistTable />
      </Card>
    </div>
  )
}
