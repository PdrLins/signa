'use client'

import Link from 'next/link'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useWatchlist, useRemoveTicker } from '@/hooks/useWatchlist'
import { WatchlistRow } from './WatchlistRow'
import { Badge } from '@/components/ui/Badge'
import { Skeleton } from '@/components/ui/Skeleton'
import { X } from 'lucide-react'
import type { Signal } from '@/types/signal'

interface WatchlistTableProps {
  signals?: Signal[]
  compact?: boolean
}

export function WatchlistTable({ signals, compact = false }: WatchlistTableProps) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const { data: items, isLoading, isError, error } = useWatchlist()
  const removeTicker = useRemoveTicker()

  if (isLoading) {
    return compact
      ? <div className="flex gap-2"><Skeleton width={80} height={28} borderRadius={8} /><Skeleton width={80} height={28} borderRadius={8} /></div>
      : (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="flex items-center gap-3">
              <Skeleton width={36} height={36} borderRadius={9} />
              <div className="flex-1 space-y-1">
                <Skeleton width={60} height={12} />
                <Skeleton width={100} height={10} />
              </div>
              <Skeleton width={50} height={14} />
            </div>
          ))}
        </div>
      )
  }

  if (isError) {
    return (
      <p className="text-sm py-2" style={{ color: theme.colors.down }}>
        {error?.message || t.watchlist.loadFailed}
      </p>
    )
  }

  if (!items?.length) {
    return (
      <p className={compact ? "text-[11px] py-1" : "text-sm text-center py-8"} style={{ color: theme.colors.textHint }}>
        {t.watchlist.empty}
      </p>
    )
  }

  // Compact mode: horizontal pill row
  if (compact) {
    return (
      <div className="flex flex-wrap gap-1.5">
        {items.map((item) => {
          const signal = signals?.find((s) => s.symbol === item.symbol)
          const scoreColor = signal?.action === 'BUY' ? theme.colors.up
            : signal?.action === 'SELL' || signal?.action === 'AVOID' ? theme.colors.down
            : theme.colors.textSub

          return (
            <Link key={item.id} href={`/signals/${item.symbol}`}>
              <div
                className="flex items-center gap-1 px-2 py-1 rounded-md transition-opacity hover:opacity-80"
                style={{ backgroundColor: theme.colors.surfaceAlt, border: `1px solid ${theme.colors.border}` }}
              >
                <span className="text-[11px] font-semibold" style={{ color: theme.colors.text }}>
                  {item.symbol}
                </span>
                {signal && (
                  <span className="text-[10px] font-bold tabular-nums" style={{ color: scoreColor }}>
                    {signal.score}
                  </span>
                )}
                <button
                  onClick={(e) => { e.preventDefault(); e.stopPropagation(); removeTicker.mutate(item.symbol) }}
                  className="opacity-30 hover:opacity-100 transition-opacity"
                >
                  <X size={10} style={{ color: theme.colors.textHint }} />
                </button>
              </div>
            </Link>
          )
        })}
      </div>
    )
  }

  // Full mode: rows
  return (
    <div>
      {items.map((item) => {
        const signal = signals?.find((s) => s.symbol === item.symbol)
        return (
          <WatchlistRow
            key={item.id}
            item={item}
            signal={signal}
            onRemove={(ticker) => removeTicker.mutate(ticker)}
          />
        )
      })}
    </div>
  )
}
