'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { client } from '@/lib/api'
import { Skeleton } from '@/components/ui/Skeleton'
import { TXN_COLOR, TXN_PAGE_SIZE, SELL_TYPES, fmtTxnDate, extractPnl, type WalletTransactionList } from './types'

export function WalletHistory() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const [expanded, setExpanded] = useState(false)
  const [limit, setLimit] = useState(TXN_PAGE_SIZE)

  const { data, isFetching } = useQuery<WalletTransactionList>({
    queryKey: ['wallet', 'transactions', limit],
    queryFn: async () =>
      (await client.get<WalletTransactionList>(`/wallet/transactions?limit=${limit}`)).data,
    enabled: expanded,
    staleTime: 30_000,
  })

  const txns = data?.transactions ?? []
  const hasMore = txns.length === limit

  return (
    <section className="space-y-0">
      {/* Day-32 editorial header with a real "click me" affordance.
          Bigger chevron in an accent-tinted circle, explicit SHOW/HIDE
          label, hover background tint, count visible at all times. */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="group w-full flex items-baseline justify-between py-3 px-2 -mx-2 transition-colors cursor-pointer rounded"
        style={{ borderBottom: `1px solid ${theme.colors.border}` }}
        onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = theme.colors.surfaceAlt }}
        onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'transparent' }}
        aria-expanded={expanded}
        aria-label={`${expanded ? 'Hide' : 'Show'} transactions`}
      >
        <div className="flex items-baseline gap-3">
          <h2
            className="text-xl"
            style={{ color: theme.colors.text, fontWeight: 500 }}
          >
            {t.wallet?.transactions ?? 'Transactions'}
          </h2>
          <span
            className="text-xs tabular-nums"
            style={{ color: theme.colors.textHint, fontFamily: 'var(--font-mono)' }}
          >
            {String(txns.length).padStart(2, '0')}{hasMore ? '+' : ''}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span
            className="text-[10px] uppercase tracking-[0.14em] transition-colors"
            style={{
              color: expanded ? theme.colors.primary : theme.colors.textSub,
              fontFamily: 'var(--font-mono)',
            }}
          >
            {expanded ? 'HIDE' : 'SHOW'}
          </span>
          <span
            className="inline-flex items-center justify-center w-7 h-7 rounded-full transition-all group-hover:scale-105"
            style={{
              backgroundColor: expanded ? theme.colors.primary + '20' : 'transparent',
              border: `1px solid ${expanded ? theme.colors.primary + '40' : theme.colors.border}`,
              color: expanded ? theme.colors.primary : theme.colors.textSub,
            }}
          >
            {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
          </span>
        </div>
      </button>

      {expanded && (
        <div className="mt-3">
          {isFetching && txns.length === 0 && (
            <Skeleton width="100%" height={120} borderRadius={8} />
          )}
          {!isFetching && txns.length === 0 && (
            <p className="text-[11px]" style={{ color: theme.colors.textHint }}>
              {t.wallet?.noTransactions ?? 'No transactions yet'}
            </p>
          )}
          {txns.length > 0 && (
            <div>
              {txns.map((tx) => {
                const colorKey = TXN_COLOR[tx.transaction_type]
                const typeColor = theme.colors[colorKey]
                const sign = tx.amount > 0 ? '+' : tx.amount < 0 ? '-' : ''

                // For sell-type rows the `amount` is gross proceeds (always
                // positive when something flowed in) but the REALIZED P&L
                // is what tells you win/loss. Surface it as its own badge
                // colored independently.
                const pnl = SELL_TYPES.has(tx.transaction_type) ? extractPnl(tx.description) : null
                const pnlColor = pnl == null
                  ? theme.colors.textHint
                  : pnl > 0
                    ? theme.colors.up
                    : pnl < 0
                      ? theme.colors.down
                      : theme.colors.textHint
                const isWin = pnl != null && pnl > 0
                const isLoss = pnl != null && pnl < 0

                // Day-33 cleanup: extract the exit reason from the
                // description text (e.g. "SELL ... (P&L $+64.06, THESIS_INVALIDATED)")
                // so we can render JUST that small tag instead of the
                // whole verbose description. For non-SELL rows we drop
                // the description entirely because it duplicates the
                // row's ticker/shares/price line.
                let exitReason: string | null = null
                if (SELL_TYPES.has(tx.transaction_type) && tx.description) {
                  const m = tx.description.match(/,\s*([A-Z_]+)\)\s*$/)
                  if (m) exitReason = m[1].replace(/_/g, ' ')
                }
                return (
                  <div
                    key={tx.id}
                    className="group relative flex items-center justify-between gap-4 py-4 pl-3 pr-2 transition-colors"
                    style={{
                      borderBottom: `1px solid ${theme.colors.border}`,
                      borderLeft: `2px solid ${typeColor}`,
                    }}
                    onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = theme.colors.surfaceAlt + '60' }}
                    onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'transparent' }}
                  >
                    <div className="flex items-center gap-3 min-w-0 flex-1">
                      {/* Type label — short, color-coded, uppercase mono */}
                      <span
                        className="text-[9px] uppercase tracking-[0.14em] tabular-nums shrink-0"
                        style={{
                          color: typeColor,
                          fontFamily: 'var(--font-mono)',
                          minWidth: '3.5rem',
                          fontWeight: 600,
                        }}
                      >
                        {tx.transaction_type.replace('_', ' ')}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-baseline gap-2.5 flex-wrap">
                          {tx.symbol && (
                            <span
                              className="text-[15px] tabular-nums"
                              style={{
                                color: theme.colors.text,
                                fontFamily: 'var(--font-mono)',
                                fontWeight: 600,
                                letterSpacing: '0.02em',
                                fontStyle: 'normal',
                              }}
                            >
                              {tx.symbol}
                            </span>
                          )}
                          {tx.shares != null && tx.shares > 0 && tx.price != null && (
                            <span
                              className="text-[11px] tabular-nums"
                              style={{ color: theme.colors.textHint, fontFamily: 'var(--font-mono)' }}
                            >
                              {tx.shares.toFixed(2)} @ ${tx.price.toFixed(2)}
                            </span>
                          )}
                          {(isWin || isLoss) && (
                            <span
                              className="text-[10px] uppercase tracking-[0.10em] tabular-nums"
                              style={{
                                color: pnlColor,
                                fontFamily: 'var(--font-mono)',
                                fontWeight: 600,
                              }}
                            >
                              {pnl! >= 0 ? '+' : '-'}${Math.abs(pnl!).toFixed(2)}
                            </span>
                          )}
                        </div>
                        <div className="flex items-center gap-2 mt-1">
                          <span
                            className="text-[10px] tabular-nums"
                            style={{ color: theme.colors.textHint, fontFamily: 'var(--font-mono)' }}
                          >
                            {fmtTxnDate(tx.created_at)}
                          </span>
                          {exitReason && (
                            <>
                              <span className="text-[10px]" style={{ color: theme.colors.textHint }}>·</span>
                              <span
                                className="text-[10px] uppercase tracking-[0.10em]"
                                style={{ color: theme.colors.textSub, fontFamily: 'var(--font-mono)' }}
                              >
                                {exitReason}
                              </span>
                            </>
                          )}
                        </div>
                      </div>
                    </div>
                    <div className="text-right shrink-0">
                      <p
                        className="text-lg tabular-nums leading-none"
                        style={{
                          color: tx.amount === 0 ? theme.colors.textHint : typeColor,
                          fontFamily: 'var(--font-mono)',
                          fontWeight: 600,
                        }}
                      >
                        {sign}${Math.abs(tx.amount).toFixed(2)}
                      </p>
                      <p
                        className="text-[10px] mt-1.5 tabular-nums"
                        style={{ color: theme.colors.textHint, fontFamily: 'var(--font-mono)' }}
                      >
                        bal ${tx.balance_after.toFixed(2)}
                      </p>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
          {hasMore && (
            <button
              onClick={() => setLimit(limit + TXN_PAGE_SIZE)}
              disabled={isFetching}
              className="w-full mt-4 text-[11px] py-2 transition-opacity hover:opacity-80 disabled:opacity-50"
              style={{
                backgroundColor: 'transparent',
                color: theme.colors.primary,
                borderTop: `1px solid ${theme.colors.border}`,
                fontFamily: 'var(--font-mono)',
                textTransform: 'uppercase',
                letterSpacing: '0.12em',
              }}
            >
              {isFetching ? '…' : `${t.brainPerf.loadMore ?? 'LOAD MORE'} ↓`}
            </button>
          )}
        </div>
      )}
    </section>
  )
}
