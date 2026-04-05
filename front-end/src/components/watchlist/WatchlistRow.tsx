'use client'

import Link from 'next/link'
import { useTheme } from '@/hooks/useTheme'
import { Badge } from '@/components/ui/Badge'
import { X } from 'lucide-react'
import type { WatchlistItem } from '@/types/watchlist'
import type { Signal } from '@/types/signal'

interface WatchlistRowProps {
  item: WatchlistItem
  signal?: Signal
  onRemove: (symbol: string) => void
}

export function WatchlistRow({ item, signal, onRemove }: WatchlistRowProps) {
  const theme = useTheme()

  const actionColor: Record<string, string> = {
    BUY: theme.colors.up,
    SELL: theme.colors.down,
    HOLD: theme.colors.warning,
    AVOID: theme.colors.down,
  }

  return (
    <div
      className="flex items-center justify-between py-3 px-1"
      style={{ borderBottom: `0.5px solid ${theme.colors.border}` }}
    >
      <Link href={`/signals/${item.symbol}`} className="flex items-center gap-3 flex-1 min-w-0">
        <div
          className="w-9 h-9 rounded-[9px] flex items-center justify-center text-[10px] font-bold shrink-0"
          style={{
            backgroundColor: theme.colors.primary + '18',
            color: theme.colors.primary,
          }}
        >
          {item.symbol.slice(0, 4)}
        </div>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <p className="text-sm font-semibold" style={{ color: theme.colors.text }}>
              {item.symbol}
            </p>
            {signal && (
              <Badge variant={signal.action === 'BUY' ? 'buy' : signal.action === 'SELL' ? 'sell' : signal.action === 'AVOID' ? 'avoid' : 'hold'}>
                {signal.action}
              </Badge>
            )}
          </div>
          {item.notes && (
            <p className="text-[11px] truncate" style={{ color: theme.colors.textSub }}>
              {item.notes}
            </p>
          )}
        </div>
      </Link>

      <div className="flex items-center gap-3 shrink-0">
        {signal && (
          <span
            className="text-[13px] font-semibold tabular-nums"
            style={{ color: actionColor[signal.action] || theme.colors.text }}
          >
            {signal.score}
          </span>
        )}
        <span className="text-[11px]" style={{ color: theme.colors.textSub }}>
          {new Date(item.added_at).toLocaleDateString('en-CA')}
        </span>
        <button
          onClick={(e) => { e.preventDefault(); onRemove(item.symbol) }}
          className="p-1 rounded-md transition-opacity hover:opacity-70"
        >
          <X size={14} style={{ color: theme.colors.textSub }} />
        </button>
      </div>
    </div>
  )
}
