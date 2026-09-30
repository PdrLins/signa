'use client'

import { memo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Pencil, Trash2 } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useToast } from '@/hooks/useToast'
import { transactionsApi } from '@/lib/api'
import { DASH, fill, shortDate } from '@/lib/insights'
import { money, num } from '@/components/holdings/format'
import { trackerErrorText } from '@/lib/trackerErrors'
import { TRANSACTIONS_KEY } from '@/hooks/useTransactions'
import { SoonBadge, useButtonStyles } from '@/components/profile/ui'
import { TransactionForm } from './TransactionForm'
import type { Account } from '@/types/accounts'
import type { Transaction, TransactionInput, TxType } from '@/types/transactions'

/** Cash direction per type: + money in, − money out, 0 = no cash (split). */
const DIRECTION: Record<TxType, 1 | -1 | 0> = {
  buy: -1, sell: 1, dividend: 1, deposit: 1, withdrawal: -1, fee: -1, split: 0,
}

export const TransactionItem = memo(function TransactionItem({ tx, accounts, canEdit }: {
  tx: Transaction
  accounts: Account[]
  canEdit: boolean
}) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const tt = t.transactionsPage
  const toast = useToast()
  const qc = useQueryClient()
  const btn = useButtonStyles()
  const [mode, setMode] = useState<'view' | 'edit' | 'delete'>('view')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: TRANSACTIONS_KEY })
    qc.invalidateQueries({ queryKey: ['holdings'] })
  }
  const save = async (body: TransactionInput) => {
    setBusy(true); setError(null)
    try {
      await transactionsApi.update(tx.id, body)
      toast.show(tt.saved, 'success', 2000)
      invalidate()
      setMode('view')
    } catch (e) {
      setError(trackerErrorText(e, t))
    } finally {
      setBusy(false)
    }
  }
  const remove = async () => {
    setBusy(true); setError(null)
    try {
      await transactionsApi.remove(tx.id)
      toast.show(tt.deleted, 'success', 2000)
      invalidate()
    } catch (e) {
      setError(trackerErrorText(e, t))
      setBusy(false)
    }
  }

  const dir = DIRECTION[tx.type]
  const date = shortDate(tx.trade_date, locale, true)
  const typeLabel = tt.types[tx.type]
  const detail = tx.type === 'split'
    ? `${tt.ratio} ${num(tx.quantity, locale)}`
    : tx.quantity != null && tx.price != null
      ? `${num(tx.quantity, locale)} × ${money(tx.price, tx.currency, locale)}`
      : tx.quantity != null ? `${num(tx.quantity, locale)}` : null
  const amountColor = dir > 0 ? theme.colors.up : theme.colors.text

  return (
    <li className="py-3 flex flex-col gap-2 min-w-0" style={{ borderTop: `1px solid ${theme.colors.border}` }}>
      <div className="flex items-start justify-between gap-3 min-w-0">
        <div className="min-w-0">
          <p className="text-[14px] flex flex-wrap items-center gap-x-2 gap-y-1" style={{ color: theme.colors.text }}>
            <span className="text-[12px] font-semibold px-2 py-0.5 rounded-full" style={{ backgroundColor: theme.colors.surfaceAlt }}>{typeLabel}</span>
            {tx.symbol && <span className="font-mono font-semibold">{tx.symbol}</span>}
            {tx.source === 'csv' && <SoonBadge label={tt.imported} />}
          </p>
          <p className="text-[12px] mt-1 flex flex-wrap gap-x-2 tabular-nums" style={{ color: theme.colors.textSub }}>
            <span>{date}</span>
            {tx.account_name && <span>{tx.account_name}</span>}
            {detail && <span>{detail}</span>}
            {!!tx.fee && <span>{tt.fee} {money(tx.fee, tx.currency, locale)}</span>}
          </p>
          {tx.note && <p className="text-[12px] mt-0.5 break-words" style={{ color: theme.colors.textHint }}>{tx.note}</p>}
        </div>
        <div className="flex items-start gap-1 shrink-0">
          <span className="text-[14px] font-semibold tabular-nums pt-2.5" style={{ color: amountColor }}>
            {tx.amount == null || dir === 0 ? DASH : `${dir > 0 ? '+' : '−'}${money(tx.amount, tx.currency, locale)}`}
          </span>
          {canEdit && mode === 'view' && (
            <>
              <button type="button" onClick={() => setMode('edit')} className={btn.icon.className} style={btn.icon.style}
                aria-label={fill(tt.editLabel, { type: typeLabel, date })}>
                <Pencil size={16} aria-hidden="true" />
              </button>
              <button type="button" onClick={() => setMode('delete')} className={btn.icon.className}
                style={{ ...btn.icon.style, color: theme.colors.down }} aria-label={fill(tt.deleteLabel, { type: typeLabel, date })}>
                <Trash2 size={16} aria-hidden="true" />
              </button>
            </>
          )}
        </div>
      </div>
      {mode === 'edit' && (
        <TransactionForm initial={tx} accounts={accounts} busy={busy} error={error} onSubmit={save}
          onCancel={() => { setMode('view'); setError(null) }} />
      )}
      {mode === 'delete' && (
        <div role="alertdialog" aria-label={tt.deleteConfirm} className="flex flex-wrap items-center gap-2">
          <p className="text-[13px] w-full" style={{ color: theme.colors.text }}>{tt.deleteConfirm}</p>
          <button type="button" disabled={busy} onClick={remove} className={btn.danger.className}
            style={{ ...btn.danger.style, border: `1px solid ${theme.colors.down}` }}>
            {busy ? t.tracker.deleting : t.tracker.delete}
          </button>
          <button type="button" onClick={() => { setMode('view'); setError(null) }} className={btn.secondary.className} style={btn.secondary.style}>
            {t.tracker.cancel}
          </button>
          {error && <p role="alert" className="text-[13px] w-full" style={{ color: theme.colors.down }}>{error}</p>}
        </div>
      )}
    </li>
  )
})
