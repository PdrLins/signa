'use client'

import { useTheme } from '@/hooks/useTheme'
import { X } from 'lucide-react'
import type { WatchlistItem } from '@/types/watchlist'

interface WatchlistRowProps {
  item: WatchlistItem
  onRemove: (symbol: string) => void
}

export function WatchlistRow({ item, onRemove }: WatchlistRowProps) {
  const theme = useTheme()

  return (
    <div
      className="flex items-center justify-between py-3 px-1"
      style={{ borderBottom: `0.5px solid ${theme.colors.border}` }}
    >
      <div className="flex items-center gap-3">
        <div
          className="w-9 h-9 rounded-[9px] flex items-center justify-center text-[10px] font-bold"
          style={{
            backgroundColor: theme.colors.primary + '18',
            color: theme.colors.primary,
          }}
        >
          {item.symbol.slice(0, 4)}
        </div>
        <div>
          <p className="text-sm font-semibold" style={{ color: theme.colors.text }}>
            {item.symbol}
          </p>
          {item.notes && (
            <p className="text-[11px]" style={{ color: theme.colors.textSub }}>
              {item.notes}
            </p>
          )}
        </div>
      </div>

      <div className="flex items-center gap-3">
        <span className="text-[11px]" style={{ color: theme.colors.textSub }}>
          {new Date(item.added_at).toLocaleDateString('en-CA')}
        </span>
        <button
          onClick={() => onRemove(item.symbol)}
          className="p-1 rounded-md transition-opacity hover:opacity-70"
        >
          <X size={14} style={{ color: theme.colors.textSub }} />
        </button>
      </div>
    </div>
  )
}
