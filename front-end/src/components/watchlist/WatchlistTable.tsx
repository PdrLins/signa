'use client'

import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useWatchlist, useRemoveTicker } from '@/hooks/useWatchlist'
import { WatchlistRow } from './WatchlistRow'
import { Skeleton } from '@/components/ui/Skeleton'

export function WatchlistTable() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const { data: items, isLoading, isError, error } = useWatchlist()
  const removeTicker = useRemoveTicker()

  if (isLoading) {
    return (
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
      <p className="text-sm py-4" style={{ color: theme.colors.down }}>
        {error?.message || t.watchlist.loadFailed}
      </p>
    )
  }

  if (!items?.length) {
    return (
      <div className="text-center py-8">
        <p className="text-sm" style={{ color: theme.colors.textSub }}>
          {t.watchlist.empty}
        </p>
      </div>
    )
  }

  return (
    <div>
      {items.map((item) => (
        <WatchlistRow
          key={item.id}
          item={item}
          onRemove={(ticker) => removeTicker.mutate(ticker)}
        />
      ))}
    </div>
  )
}
