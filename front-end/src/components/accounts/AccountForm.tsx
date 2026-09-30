'use client'

import { useId, useMemo, useState } from 'react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { parseAmount } from '@/lib/trackerErrors'
import { currencyName } from '@/lib/intlNames'
import { SoonBadge, useButtonStyles, useFieldStyle } from '@/components/profile/ui'
import type { Account, AccountInput, Person } from '@/types/accounts'

/** Create / edit one account. The type select only appears when the user's
 *  country has account types (CA/US) AND the plan allows them. */
export function AccountForm({ initial, people, currencies, homeCurrency, types, typeLocked, busy, error, onSubmit, onCancel }: {
  initial?: Account
  people: Person[]
  currencies: string[]
  homeCurrency: string
  /** allowed types for the user's country ([] outside CA/US) */
  types: string[]
  /** CA/US but the plan has no action.accounts.type → show a Premium hint */
  typeLocked: boolean
  busy: boolean
  error: string | null
  onSubmit: (body: AccountInput) => void
  onCancel?: () => void
}) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const ta = t.accountsPage
  const f = useFieldStyle()
  const btn = useButtonStyles()
  const ids = { name: useId(), person: useId(), ccy: useId(), cash: useId(), type: useId() }
  const [name, setName] = useState(initial?.name ?? '')
  const [personId, setPersonId] = useState(initial?.person_id ?? '')
  const [currency, setCurrency] = useState(initial?.currency ?? homeCurrency)
  const [cash, setCash] = useState(initial ? String(initial.cash_balance ?? 0) : '')
  const [type, setType] = useState(initial?.account_type ?? '')
  const cashN = parseAmount(cash)
  const cashBad = Number.isNaN(cashN)
  const ccyList = useMemo(() => {
    const set = new Set(currencies.length ? currencies : [homeCurrency, 'CAD', 'USD'])
    set.add(currency)
    return Array.from(set).sort()
  }, [currencies, homeCurrency, currency])
  const showType = types.length > 0 && !typeLocked

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim() || cashBad) return
    const body: AccountInput = { name: name.trim(), currency, cash_balance: cashN ?? 0 }
    if (!initial || (initial.person_id ?? '') !== personId) body.person_id = personId || null
    if (showType && (initial?.account_type ?? '') !== type) body.account_type = type || null
    onSubmit(body)
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-3" aria-label={initial ? `${ta.editAccount.replace('{name}', initial.name)}` : ta.addAccount}>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        <label htmlFor={ids.name} className={`${f.label} sm:col-span-2`} style={{ color: f.labelColor }}>
          {ta.name}
          <input id={ids.name} value={name} maxLength={60} required autoFocus={!initial}
            placeholder={ta.namePlaceholder} onChange={(e) => setName(e.target.value)} className={f.input} style={f.style} />
        </label>
        {people.length > 0 && (
          <label htmlFor={ids.person} className={f.label} style={{ color: f.labelColor }}>
            {ta.person}
            <select id={ids.person} value={personId} onChange={(e) => setPersonId(e.target.value)} className={f.input} style={f.style}>
              <option value="">{ta.personNone}</option>
              {people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </label>
        )}
        <label htmlFor={ids.ccy} className={f.label} style={{ color: f.labelColor }}>
          {ta.currency}
          <select id={ids.ccy} value={currency} onChange={(e) => setCurrency(e.target.value)} className={f.input} style={f.style}>
            {ccyList.map((c) => <option key={c} value={c}>{currencyName(c, locale)}</option>)}
          </select>
        </label>
        <label htmlFor={ids.cash} className={f.label} style={{ color: f.labelColor }}>
          {ta.cash} ({currency})
          <input id={ids.cash} inputMode="decimal" value={cash} placeholder="0" onChange={(e) => setCash(e.target.value)}
            aria-invalid={cashBad || undefined} className={`${f.input} tabular-nums`}
            style={{ ...f.style, borderColor: cashBad ? theme.colors.down : theme.colors.border }} />
        </label>
        {showType && (
          <label htmlFor={ids.type} className={f.label} style={{ color: f.labelColor }}>
            {ta.type}
            <select id={ids.type} value={type} onChange={(e) => setType(e.target.value)} className={f.input} style={f.style}>
              <option value="">{ta.typeNone}</option>
              {types.map((ty) => <option key={ty} value={ty}>{(ta.types as Record<string, string>)[ty] ?? ty}</option>)}
            </select>
          </label>
        )}
      </div>
      {types.length > 0 && typeLocked && (
        <p className="text-[12px] flex flex-wrap items-center gap-2" style={{ color: theme.colors.textSub }}>
          <SoonBadge label={t.tracker.premium} tone="primary" />{ta.typePremium}
        </p>
      )}
      {cashBad && <p role="alert" className="text-[12px]" style={{ color: theme.colors.down }}>{t.tracker.errors.invalid_cash_balance}</p>}
      {error && <p role="alert" className="text-[13px]" style={{ color: theme.colors.down }}>{error}</p>}
      <div className="flex flex-wrap gap-2">
        <button type="submit" disabled={busy || !name.trim() || cashBad} className={btn.primary.className} style={btn.primary.style}>
          {busy ? t.tracker.saving : initial ? t.tracker.save : ta.addAccount}
        </button>
        {onCancel && (
          <button type="button" onClick={onCancel} className={btn.secondary.className} style={btn.secondary.style}>
            {t.tracker.cancel}
          </button>
        )}
      </div>
    </form>
  )
}
