'use client'

import { useId, useMemo, useState } from 'react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { parseAmount } from '@/lib/trackerErrors'
import { useButtonStyles, useFieldStyle } from '@/components/profile/ui'
import { TX_TYPES, type Transaction, type TransactionInput, type TxType } from '@/types/transactions'
import type { Account } from '@/types/accounts'

type FieldKey = 'symbol' | 'quantity' | 'price' | 'amount' | 'fee'
type Need = 'required' | 'optional' | 'hidden'

/** Which fields each type uses (mirrors transactions_service.validate_transaction). */
const FIELDS: Record<TxType, Record<FieldKey, Need>> = {
  buy: { symbol: 'required', quantity: 'required', price: 'required', amount: 'optional', fee: 'optional' },
  sell: { symbol: 'required', quantity: 'required', price: 'required', amount: 'optional', fee: 'optional' },
  dividend: { symbol: 'required', quantity: 'optional', price: 'hidden', amount: 'required', fee: 'optional' },
  split: { symbol: 'required', quantity: 'required', price: 'hidden', amount: 'hidden', fee: 'hidden' },
  deposit: { symbol: 'hidden', quantity: 'hidden', price: 'hidden', amount: 'required', fee: 'optional' },
  withdrawal: { symbol: 'hidden', quantity: 'hidden', price: 'hidden', amount: 'required', fee: 'optional' },
  fee: { symbol: 'optional', quantity: 'hidden', price: 'hidden', amount: 'required', fee: 'hidden' },
}

function todayIso(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const str = (v: number | null | undefined) => (v === null || v === undefined ? '' : String(v))

export function TransactionForm({ initial, accounts, defaultAccountId = '', defaultSymbol = '', busy, error, onSubmit, onCancel }: {
  initial?: Transaction
  accounts: Account[]
  defaultAccountId?: string
  /** prefill for a new transaction (e.g. "Record a trade" from a holding) */
  defaultSymbol?: string
  busy: boolean
  error: string | null
  onSubmit: (body: TransactionInput) => void
  onCancel: () => void
}) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const tt = t.transactionsPage
  const f = useFieldStyle()
  const btn = useButtonStyles()
  const ids = {
    type: useId(), date: useId(), account: useId(), symbol: useId(), qty: useId(), price: useId(),
    amount: useId(), ccy: useId(), fee: useId(), note: useId(),
  }
  const [type, setType] = useState<TxType>(initial?.type ?? 'buy')
  const [date, setDate] = useState(initial?.trade_date ?? todayIso())
  const [accountId, setAccountId] = useState(initial?.account_id ?? defaultAccountId)
  const [symbol, setSymbol] = useState(initial?.symbol ?? defaultSymbol)
  const [qty, setQty] = useState(str(initial?.quantity))
  const [price, setPrice] = useState(str(initial?.price))
  const [amount, setAmount] = useState(str(initial?.amount))
  const [currency, setCurrency] = useState(initial?.currency ?? '')
  const [fee, setFee] = useState(initial?.fee ? String(initial.fee) : '')
  const [note, setNote] = useState(initial?.note ?? '')
  const need = FIELDS[type]

  const nums = useMemo(() => ({
    quantity: parseAmount(qty), price: parseAmount(price), amount: parseAmount(amount), fee: parseAmount(fee),
  }), [qty, price, amount, fee])
  const bad = (k: keyof typeof nums) => need[k] !== 'hidden' && (Number.isNaN(nums[k]) || (nums[k] ?? 0) < 0)
  const anyBad = bad('quantity') || bad('price') || bad('amount') || bad('fee')
  const ccyBad = !!currency && !/^[A-Za-z]{3}$/.test(currency)

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    if (anyBad || ccyBad) return
    const val = (k: keyof typeof nums) => (need[k] === 'hidden' ? null : nums[k])
    onSubmit({
      type,
      trade_date: date,
      account_id: accountId || null,
      symbol: need.symbol === 'hidden' ? null : symbol.trim().toUpperCase() || null,
      quantity: val('quantity'),
      price: val('price'),
      amount: val('amount'),
      fee: need.fee === 'hidden' ? null : nums.fee,
      currency: currency.trim().toUpperCase() || null,
      note: note.trim() || null,
    })
  }

  const numField = (k: 'quantity' | 'price' | 'amount' | 'fee', id: string, label: string, value: string, set: (v: string) => void, help?: string) =>
    need[k] === 'hidden' ? null : (
      <label key={k} htmlFor={id} className={f.label} style={{ color: f.labelColor }}>
        {label}{need[k] === 'optional' ? ` (${t.tracker.optional})` : ''}
        <input id={id} inputMode="decimal" value={value} onChange={(e) => set(e.target.value)} required={need[k] === 'required' && k !== 'price'}
          aria-invalid={bad(k) || undefined} aria-describedby={help ? `${id}-help` : undefined}
          className={`${f.input} tabular-nums`} style={{ ...f.style, borderColor: bad(k) ? theme.colors.down : theme.colors.border }} />
        {help && <span id={`${id}-help`} style={{ color: theme.colors.textHint }}>{help}</span>}
      </label>
    )

  return (
    <form onSubmit={submit} className="flex flex-col gap-3" aria-label={initial ? tt.editTitle : tt.addTitle}>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
        <label htmlFor={ids.type} className={f.label} style={{ color: f.labelColor }}>
          {tt.type}
          <select id={ids.type} value={type} onChange={(e) => setType(e.target.value as TxType)} className={f.input} style={f.style}>
            {TX_TYPES.map((ty) => <option key={ty} value={ty}>{tt.types[ty]}</option>)}
          </select>
        </label>
        <label htmlFor={ids.date} className={f.label} style={{ color: f.labelColor }}>
          {tt.date}
          <input id={ids.date} type="date" required value={date} max={todayIso()} onChange={(e) => setDate(e.target.value)}
            className={f.input} style={f.style} />
        </label>
        <label htmlFor={ids.account} className={`${f.label} col-span-2 sm:col-span-1`} style={{ color: f.labelColor }}>
          {tt.account}
          <select id={ids.account} value={accountId} onChange={(e) => setAccountId(e.target.value)} className={f.input} style={f.style}>
            <option value="">{tt.noAccount}</option>
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </label>
        {need.symbol !== 'hidden' && (
          <label htmlFor={ids.symbol} className={f.label} style={{ color: f.labelColor }}>
            {tt.symbol}{need.symbol === 'optional' ? ` (${t.tracker.optional})` : ''}
            <input id={ids.symbol} value={symbol} maxLength={24} required={need.symbol === 'required'} autoCapitalize="characters"
              autoCorrect="off" spellCheck={false} placeholder={tt.symbolPlaceholder} onChange={(e) => setSymbol(e.target.value)}
              className={`${f.input} font-mono`} style={f.style} />
          </label>
        )}
        {numField('quantity', ids.qty, type === 'split' ? tt.ratio : tt.quantity, qty, setQty, type === 'split' ? tt.ratioHelp : undefined)}
        {numField('price', ids.price, tt.price, price, setPrice)}
        {numField('amount', ids.amount, tt.amount, amount, setAmount, tt.amountHelp)}
        {numField('fee', ids.fee, tt.fee, fee, setFee)}
        <label htmlFor={ids.ccy} className={f.label} style={{ color: f.labelColor }}>
          {tt.currency} ({t.tracker.optional})
          <input id={ids.ccy} value={currency} maxLength={3} autoCapitalize="characters" placeholder="CAD"
            onChange={(e) => setCurrency(e.target.value.toUpperCase())} aria-invalid={ccyBad || undefined}
            className={`${f.input} font-mono`} style={{ ...f.style, borderColor: ccyBad ? theme.colors.down : theme.colors.border }} />
        </label>
        <label htmlFor={ids.note} className={`${f.label} col-span-2 sm:col-span-3`} style={{ color: f.labelColor }}>
          {tt.note} ({t.tracker.optional})
          <input id={ids.note} value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} className={f.input} style={f.style} />
        </label>
      </div>
      {(anyBad || ccyBad) && (
        <p role="alert" className="text-[12px]" style={{ color: theme.colors.down }}>
          {ccyBad ? t.tracker.errors.invalid_currency : t.tracker.errors.invalid_number}
        </p>
      )}
      {error && <p role="alert" className="text-[13px]" style={{ color: theme.colors.down }}>{error}</p>}
      <div className="flex flex-wrap gap-2">
        <button type="submit" disabled={busy || anyBad || ccyBad} className={btn.primary.className} style={btn.primary.style}>
          {busy ? t.tracker.saving : initial ? t.tracker.save : tt.add}
        </button>
        <button type="button" onClick={onCancel} className={btn.secondary.className} style={btn.secondary.style}>{t.tracker.cancel}</button>
      </div>
    </form>
  )
}
