'use client'

import Link from 'next/link'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { Panel } from '@/components/insights/Panel'
import { fill, nativePrice, signedPct } from '@/lib/insights'
import type { TodayPosition } from '@/types/insights'

export function OpenPositionsCard({ positions }: { positions: TodayPosition[] }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const p = t.today.positions

  return (
    <Panel
      title={p.title}
      right={
        <Link
          href="/positions"
          aria-label={p.allLabel}
          className="text-[13px] hover:underline focus-visible:outline focus-visible:outline-2 rounded"
          style={{ color: theme.colors.accent, outlineColor: theme.colors.primary }}
        >
          {p.all} →
        </Link>
      }
    >
      {positions.length === 0 ? (
        <p className="text-sm" style={{ color: theme.colors.textSub }}>{p.empty}</p>
      ) : (
        <ul className="flex flex-col gap-3">
          {positions.map((pos) => {
            const pnlColor = pos.pnl_pct == null ? theme.colors.textSub : pos.pnl_pct > 0 ? theme.colors.up : theme.colors.down
            const pct = pos.progress != null ? Math.round(pos.progress * 100) : null
            const days = pos.days_held == null ? '' : pos.days_held <= 0 ? p.openedToday : fill(p.day, { n: pos.days_held })
            return (
              <li key={pos.id}>
                <Link
                  href={`/signals/${encodeURIComponent(pos.symbol)}`}
                  className="flex flex-col gap-2 p-3 rounded-xl transition-opacity hover:opacity-90 focus-visible:outline focus-visible:outline-2"
                  style={{ backgroundColor: theme.colors.surfaceAlt, outlineColor: theme.colors.primary, color: theme.colors.text }}
                >
                  <span className="flex justify-between">
                    <span className="text-[14px] font-medium" style={{ fontFamily: 'var(--font-mono)' }}>{pos.symbol}</span>
                    <span className="text-[14px] tabular-nums" style={{ fontFamily: 'var(--font-mono)', color: pnlColor }}>{signedPct(pos.pnl_pct, 1)}</span>
                  </span>
                  {pct != null ? (
                    <span
                      className="relative block h-1.5 rounded-full"
                      style={{ backgroundColor: theme.colors.bg }}
                      role="img"
                      aria-label={fill(p.barLabel, { symbol: pos.symbol, pct })}
                    >
                      <span className="absolute left-0 top-0 h-1.5 rounded-full" style={{ width: `${pct}%`, backgroundColor: theme.colors.primary + '59' }} />
                      <span className="absolute -top-[3px] w-0.5 h-3" style={{ left: `calc(${pct}% - 1px)`, backgroundColor: theme.colors.text }} />
                    </span>
                  ) : (
                    <span className="text-[11px]" style={{ color: theme.colors.textSub }}>{pos.stop == null || pos.target == null ? p.noLevels : ''}</span>
                  )}
                  <span className="flex justify-between text-[11px]" style={{ color: theme.colors.textSub }}>
                    <span>{p.stop} <span style={{ fontFamily: 'var(--font-mono)' }}>{nativePrice(pos.stop, pos.symbol, pos.currency)}</span></span>
                    <span>{days}</span>
                    <span>{p.target} <span style={{ fontFamily: 'var(--font-mono)' }}>{nativePrice(pos.target, pos.symbol, pos.currency)}</span></span>
                  </span>
                </Link>
              </li>
            )
          })}
        </ul>
      )}
    </Panel>
  )
}
