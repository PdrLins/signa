'use client'

import { memo, useId, useState } from 'react'
import { Pencil, Trash2 } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useToast } from '@/hooks/useToast'
import { accountsApi } from '@/lib/api'
import { fill } from '@/lib/insights'
import { money } from '@/components/holdings/format'
import { trackerErrorCode, trackerErrorText } from '@/lib/trackerErrors'
import { toHoldingsError } from '@/hooks/useHoldings'
import { useInvalidateAccounts } from '@/hooks/useAccounts'
import { useButtonStyles, useFieldStyle } from '@/components/profile/ui'
import { AccountForm } from './AccountForm'
import type { Account, AccountInput, Person } from '@/types/accounts'

export const AccountRow = memo(function AccountRow({ account, others, people, currencies, homeCurrency, types, typeLocked, canEdit }: {
  account: Account
  /** the user's other accounts (move targets) */
  others: Account[]
  people: Person[]
  currencies: string[]
  homeCurrency: string
  types: string[]
  typeLocked: boolean
  canEdit: boolean
}) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const ta = t.accountsPage
  const toast = useToast()
  const invalidate = useInvalidateAccounts()
  const btn = useButtonStyles()
  const f = useFieldStyle()
  const moveId = useId()
  const [mode, setMode] = useState<'view' | 'edit' | 'delete'>('view')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // holdings still inside (from the row, or from a 409 account_has_holdings)
  const [inside, setInside] = useState(account.holdings_count)
  const [moveTo, setMoveTo] = useState(others[0]?.id ?? '')

  const save = async (body: AccountInput) => {
    setBusy(true)
    setError(null)
    try {
      await accountsApi.update(account.id, body)
      toast.show(ta.updated, 'success', 2000)
      invalidate()
      setMode('view')
    } catch (e) {
      setError(trackerErrorText(e, t))
    } finally {
      setBusy(false)
    }
  }

  const remove = async (opts?: { moveTo?: string; force?: boolean }) => {
    setBusy(true)
    setError(null)
    try {
      const res = await accountsApi.remove(account.id, opts)
      toast.show(res.moved_holdings ? `${ta.deleted} · ${fill(ta.moved, { n: res.moved_holdings })}` : ta.deleted, 'success')
      invalidate()
    } catch (e) {
      if (trackerErrorCode(e) === 'account_has_holdings') {
        const n = Number(toHoldingsError(e).extra?.holdings ?? 0)
        setInside(n || Math.max(1, inside))
      } else {
        setError(trackerErrorText(e, t))
      }
      setBusy(false)
    }
  }

  const typeLabel = account.account_type ? ((ta.types as Record<string, string>)[account.account_type] ?? account.account_type) : null

  return (
    <li className="rounded-xl p-3 flex flex-col gap-3 min-w-0" style={{ backgroundColor: theme.colors.surfaceAlt }}>
      <div className="flex items-start justify-between gap-3 min-w-0">
        <div className="min-w-0">
          <p className="text-[15px] font-semibold truncate" style={{ color: theme.colors.text }}>{account.name}</p>
          <p className="text-[12px] flex flex-wrap gap-x-2" style={{ color: theme.colors.textSub }}>
            {account.person_name && <span>{account.person_name}</span>}
            {typeLabel && <span>{typeLabel}</span>}
            <span>{account.currency}</span>
            <span className="tabular-nums">{fill(ta.cashLine, { amount: money(account.cash_balance, account.currency, locale) })}</span>
            <span>{fill(ta.holdingsCount, { n: account.holdings_count })}</span>
          </p>
        </div>
        {canEdit && mode === 'view' && (
          <div className="flex gap-1 shrink-0">
            <button type="button" onClick={() => { setMode('edit'); setError(null) }} className={btn.icon.className} style={btn.icon.style}
              aria-label={fill(ta.editAccount, { name: account.name })}>
              <Pencil size={16} aria-hidden="true" />
            </button>
            <button type="button" onClick={() => { setMode('delete'); setError(null); setInside(account.holdings_count) }}
              className={btn.icon.className} style={{ ...btn.icon.style, color: theme.colors.down }}
              aria-label={fill(ta.deleteAccount, { name: account.name })}>
              <Trash2 size={16} aria-hidden="true" />
            </button>
          </div>
        )}
      </div>

      {mode === 'edit' && (
        <AccountForm initial={account} people={people} currencies={currencies} homeCurrency={homeCurrency}
          types={types} typeLocked={typeLocked} busy={busy} error={error} onSubmit={save} onCancel={() => setMode('view')} />
      )}

      {mode === 'delete' && (
        <div role="alertdialog" aria-label={fill(ta.deleteConfirm, { name: account.name })} className="flex flex-col gap-2">
          {inside > 0 ? (
            <>
              <p className="text-[13px]" style={{ color: theme.colors.text }}>{fill(ta.hasHoldings, { name: account.name, n: inside })}</p>
              {others.length > 0 && (
                <div className="flex flex-wrap items-end gap-2">
                  <label htmlFor={moveId} className={`${f.label} flex-1 min-w-[180px]`} style={{ color: f.labelColor }}>
                    {ta.moveTo}
                    <select id={moveId} value={moveTo} onChange={(e) => setMoveTo(e.target.value)} className={f.input} style={f.style}>
                      {others.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
                    </select>
                  </label>
                  <button type="button" disabled={busy || !moveTo} onClick={() => remove({ moveTo })}
                    className={btn.primary.className} style={btn.primary.style}>
                    {busy ? t.tracker.deleting : ta.moveAndDelete}
                  </button>
                </div>
              )}
              <div className="flex flex-wrap gap-2">
                <button type="button" disabled={busy} onClick={() => remove({ force: true })}
                  className={btn.danger.className} style={{ ...btn.danger.style, border: `1px solid ${theme.colors.down}` }}>
                  {ta.forceDelete}
                </button>
                <button type="button" disabled={busy} onClick={() => setMode('view')} className={btn.secondary.className} style={btn.secondary.style}>
                  {t.tracker.cancel}
                </button>
              </div>
            </>
          ) : (
            <>
              <p className="text-[13px]" style={{ color: theme.colors.text }}>{fill(ta.deleteConfirm, { name: account.name })}</p>
              <div className="flex flex-wrap gap-2">
                <button type="button" disabled={busy} onClick={() => remove()}
                  className={btn.danger.className} style={{ ...btn.danger.style, border: `1px solid ${theme.colors.down}` }}>
                  {busy ? t.tracker.deleting : t.tracker.delete}
                </button>
                <button type="button" disabled={busy} onClick={() => setMode('view')} className={btn.secondary.className} style={btn.secondary.style}>
                  {t.tracker.cancel}
                </button>
              </div>
            </>
          )}
          {error && <p role="alert" className="text-[13px]" style={{ color: theme.colors.down }}>{error}</p>}
        </div>
      )}
    </li>
  )
})
