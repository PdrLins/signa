'use client'

import { useState } from 'react'
import { useTheme } from '@/hooks/useTheme'
import { useAddTicker } from '@/hooks/useWatchlist'
import { WatchlistTable } from '@/components/watchlist/WatchlistTable'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'

export default function WatchlistPage() {
  const theme = useTheme()
  const [ticker, setTicker] = useState('')
  const addTicker = useAddTicker()

  const handleAdd = (e: React.FormEvent) => {
    e.preventDefault()
    const value = ticker.trim().toUpperCase()
    if (!value) return
    addTicker.mutate(value, {
      onSuccess: () => setTicker(''),
    })
  }

  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-bold" style={{ color: theme.colors.text }}>
        Watchlist
      </h1>

      {/* Add ticker */}
      <form onSubmit={handleAdd} className="flex gap-2">
        <input
          type="text"
          value={ticker}
          onChange={(e) => setTicker(e.target.value)}
          placeholder="Enter ticker (e.g. AAPL)"
          className="flex-1 rounded-[11px] px-4 py-3 text-sm outline-none"
          style={{
            backgroundColor: theme.colors.surfaceAlt,
            color: theme.colors.text,
            border: `0.5px solid ${theme.colors.border}`,
          }}
        />
        <Button type="submit" disabled={!ticker.trim() || addTicker.isPending}>
          {addTicker.isPending ? 'Adding...' : 'Add'}
        </Button>
      </form>

      {addTicker.isError && (
        <p className="text-sm" style={{ color: theme.colors.down }}>
          {addTicker.error?.message || 'Failed to add ticker'}
        </p>
      )}

      <Card padding="16px">
        <WatchlistTable />
      </Card>
    </div>
  )
}
