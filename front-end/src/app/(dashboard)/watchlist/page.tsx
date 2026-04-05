'use client'

import { useState } from 'react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useWatchlist, useAddTicker } from '@/hooks/useWatchlist'
import { useToast } from '@/hooks/useToast'
import { WatchlistTable } from '@/components/watchlist/WatchlistTable'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Sidebar } from '@/components/layout/Sidebar'

export default function WatchlistPage() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const toast = useToast()
  const { data: items } = useWatchlist()
  const [ticker, setTicker] = useState('')
  const addTicker = useAddTicker()

  const handleAdd = (e: React.FormEvent) => {
    e.preventDefault()
    const value = ticker.trim().toUpperCase()
    if (!value) return
    addTicker.mutate(value, {
      onSuccess: () => {
        setTicker('')
        toast.show(`${value} ${t.signal.addedToWatchlist}`, 'success')
      },
      onError: (err) => {
        toast.show(err?.message || t.watchlist.addFailed, 'error')
      },
    })
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold" style={{ color: theme.colors.text }}>{t.watchlist.title}</h1>
        {items && (
          <p className="text-sm mt-1" style={{ color: theme.colors.textSub }}>
            {items.length} {items.length === 1 ? 'ticker' : 'tickers'}
          </p>
        )}
      </div>

      <form onSubmit={handleAdd} className="flex gap-2">
        <input
          type="text"
          value={ticker}
          onChange={(e) => setTicker(e.target.value)}
          placeholder={t.watchlist.placeholder}
          className="flex-1 rounded-[11px] px-4 py-3 text-sm outline-none"
          style={{
            backgroundColor: theme.colors.surfaceAlt,
            color: theme.colors.text,
            border: `0.5px solid ${theme.colors.border}`,
          }}
        />
        <Button type="submit" disabled={!ticker.trim() || addTicker.isPending}>
          {addTicker.isPending ? t.watchlist.adding : t.watchlist.add}
        </Button>
      </form>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_300px] gap-6 items-start">
        <div className="space-y-5">
          <Card padding="16px">
            <WatchlistTable />
          </Card>
        </div>
        <div className="sticky top-6 hidden lg:block">
          <Sidebar />
        </div>
      </div>
    </div>
  )
}
