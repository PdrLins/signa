'use client'

import { useState, useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { client } from '@/lib/api'
import { formatMoney } from '@/lib/utils'
import { Card } from '@/components/ui/Card'
import type { WalletSummary } from './types'

// ── Wallet Card (Day 15) ──
// Inline — no modal. Pedro's design preference is "inline editing, no
// modals" (memory). Deposit / withdraw toggle an input row in-place.
//
// Self-fetches via its own ['wallet'] query so deposit/withdraw can
// invalidate just this slice — the full dashboard doesn't refetch when
// the user funds the wallet.

export function WalletCard() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const queryClient = useQueryClient()

  const { data: wallet } = useQuery<WalletSummary>({
    queryKey: ['wallet'],
    queryFn: async () => (await client.get<WalletSummary>('/wallet')).data,
    staleTime: 30_000,
  })

  const [mode, setMode] = useState<'idle' | 'deposit' | 'withdraw'>('idle')
  const [amount, setAmount] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Clear the error whenever the user opens a new editor (deposit /
  // withdraw) or types — a stale "insufficient balance" from a prior
  // attempt shouldn't reappear on the next open.
  const openMode = useCallback((next: 'deposit' | 'withdraw') => {
    setError(null)
    setAmount('')
    setMode(next)
  }, [])

  const submit = useCallback(async () => {
    setError(null)
    const parsed = parseFloat(amount)
    if (!Number.isFinite(parsed) || parsed <= 0) {
      setError(t.wallet?.invalidAmount ?? 'Enter a positive amount')
      return
    }
    setBusy(true)
    try {
      const path = mode === 'deposit' ? '/wallet/deposit' : '/wallet/withdraw'
      await client.post(path, { amount: parsed })
      // Invalidate the wallet slice first (this card re-renders instantly);
      // the full summary key has other consumers (widgets, other pages)
      // that need the refresh but shouldn't block the user's feedback.
      await queryClient.invalidateQueries({ queryKey: ['wallet'] })
      queryClient.invalidateQueries({ queryKey: ['stats', 'virtual-portfolio'] })
      setAmount('')
      setMode('idle')
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? (t.wallet?.requestFailed ?? 'Request failed'))
    } finally {
      setBusy(false)
    }
  }, [amount, mode, queryClient, t.wallet])

  const cancel = useCallback(() => {
    setMode('idle')
    setAmount('')
    setError(null)
  }, [])

  if (!wallet) return null

  // Day-33: roiColor/roiSign removed — the Portfolio sub-card that used
  // them was dropped (it duplicated the hero). ROI now lives on the hero
  // line only.
  // Holdings = mark-to-market of ALL open brain positions. Can legitimately
  // go negative if open SHORTs are losing more than LONGs are winning —
  // don't clamp; show the truth.
  const holdings = wallet.open_positions_value

  return (
    <Card>
      {/* Hero: WALLET = spendable cash (Pocket). Doesn't move unless you
          deposit, withdraw, or a trade settles. Portfolio / Holdings /
          Reserved live as secondary panels below — those change with the
          market, so they're deliberately NOT the big number. */}
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <p className="text-[10px] uppercase tracking-wide mb-1" style={{ color: theme.colors.textHint }}>
            {t.wallet?.title ?? 'Brain Wallet'}
          </p>
          <div className="flex items-baseline gap-2 flex-wrap">
            <p className="text-2xl font-bold tabular-nums" style={{ color: theme.colors.text }}>
              {formatMoney(wallet.balance)}
            </p>
            <span className="text-[11px]" style={{ color: theme.colors.textHint }}>
              {t.wallet?.spendable ?? 'spendable'}
            </span>
          </div>
        </div>
        {mode === 'idle' && (
          <div className="flex items-center gap-1.5 shrink-0">
            <button
              onClick={() => openMode('deposit')}
              className="text-[10px] font-semibold px-2.5 py-1.5 rounded-lg transition-opacity hover:opacity-80"
              style={{ backgroundColor: theme.colors.up + '18', color: theme.colors.up }}
              aria-label={t.wallet?.ariaDepositFunds ?? 'Deposit funds'}
            >
              + {t.wallet?.deposit ?? 'Deposit'}
            </button>
            {wallet.balance > 0 && (
              <button
                onClick={() => openMode('withdraw')}
                className="text-[10px] font-semibold px-2.5 py-1.5 rounded-lg transition-opacity hover:opacity-80"
                style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.textSub, border: `1px solid ${theme.colors.border}` }}
                aria-label={t.wallet?.ariaWithdrawFunds ?? 'Withdraw funds'}
              >
                − {t.wallet?.withdraw ?? 'Withdraw'}
              </button>
            )}
          </div>
        )}
      </div>

      {/* Day-33 slim: dropped the Portfolio sub-card — it duplicated the
          hero's portfolio value. Now just Holdings + Reserved (when > 0)
          as a small inline strip. Pocket is already shown above. */}
      {(holdings > 0 || wallet.collateral_reserved > 0) && (
        <div className="flex items-baseline gap-5 text-[11px] mb-2 mt-1" style={{ fontFamily: 'var(--font-mono)' }}>
          {holdings > 0 && (
            <div>
              <span style={{ color: theme.colors.textHint }}>HOLDINGS </span>
              <span style={{ color: theme.colors.text, fontWeight: 600 }}>{formatMoney(holdings)}</span>
            </div>
          )}
          {wallet.collateral_reserved > 0 && (
            <div>
              <span style={{ color: theme.colors.textHint }}>RESERVED </span>
              <span style={{ color: theme.colors.warning, fontWeight: 600 }}>{formatMoney(wallet.collateral_reserved)}</span>
            </div>
          )}
        </div>
      )}

      {/* Inline deposit / withdraw editor */}
      {mode !== 'idle' && (
        <div
          className="mt-2 rounded-lg p-3 flex items-center gap-2 flex-wrap"
          style={{ backgroundColor: theme.colors.surfaceAlt, border: `1px solid ${theme.colors.border}` }}
        >
          <span className="text-[10px] font-semibold uppercase tracking-wide" style={{ color: theme.colors.textHint }}>
            {mode === 'deposit' ? (t.wallet?.depositAmount ?? 'Deposit amount') : (t.wallet?.withdrawAmount ?? 'Withdraw amount')}
          </span>
          <input
            type="number"
            value={amount}
            autoFocus
            min="0"
            step="0.01"
            placeholder="0.00"
            onChange={(e) => {
              setAmount(e.target.value)
              // Typing clears the previous-attempt error so it doesn't
              // stick around looking like it relates to the new value.
              if (error) setError(null)
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !busy) submit()
              if (e.key === 'Escape') cancel()
            }}
            className="text-[12px] font-bold tabular-nums px-2 py-1 rounded flex-1 min-w-[80px] outline-none"
            style={{
              backgroundColor: theme.colors.surface,
              color: theme.colors.text,
              border: `1px solid ${theme.colors.border}`,
            }}
            aria-label={t.wallet?.ariaAmount ?? 'Amount'}
          />
          <button
            onClick={submit}
            disabled={busy || !amount}
            className="text-[10px] font-semibold px-3 py-1.5 rounded-lg transition-opacity hover:opacity-80 disabled:opacity-40"
            style={{
              backgroundColor: mode === 'deposit' ? theme.colors.up : theme.colors.warning,
              color: '#fff',
            }}
          >
            {busy ? '…' : mode === 'deposit' ? (t.wallet?.confirmDeposit ?? 'Add Funds') : (t.wallet?.confirmWithdraw ?? 'Withdraw')}
          </button>
          <button
            onClick={cancel}
            disabled={busy}
            className="text-[10px] px-2 py-1.5 rounded-lg transition-opacity hover:opacity-80"
            style={{ color: theme.colors.textHint }}
            aria-label={t.wallet?.ariaCancel ?? 'Cancel'}
          >
            {t.wallet?.cancel ?? 'Cancel'}
          </button>
          {error && (
            <p className="text-[10px] w-full" style={{ color: theme.colors.down }}>{error}</p>
          )}
        </div>
      )}

      {wallet.initial_deposit === 0 && mode === 'idle' && (
        <p className="text-[10px] mt-2" style={{ color: theme.colors.textHint }}>
          {t.wallet?.emptyHint ?? 'Deposit funds to let the brain open wallet-sized trades. Until then, new entries are skipped.'}
        </p>
      )}
    </Card>
  )
}
