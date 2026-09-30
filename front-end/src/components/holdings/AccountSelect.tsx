'use client'

import { useId, useState } from 'react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useToast } from '@/hooks/useToast'
import { useAccess } from '@/hooks/useAccess'
import { useAccounts, useInvalidateAccounts } from '@/hooks/useAccounts'
import { accountsApi } from '@/lib/api'
import { fill } from '@/lib/insights'
import { trackerErrorText } from '@/lib/trackerErrors'

const NEW = '__new__'

/** Account picker for holdings: the user's accounts + "No account" and,
 *  when allowed, "Add account…" (inline name field, creates it and selects
 *  it). Renders nothing when accounts aren't available (before migration 013). */
export function AccountSelect({ value, onChange, label, className, allowCreate = true }: {
  value: string
  onChange: (accountId: string) => void
  label?: string
  className?: string
  allowCreate?: boolean
}) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const tha = t.holdings.accounts
  const toast = useToast()
  const { can } = useAccess()
  const q = useAccounts()
  const invalidate = useInvalidateAccounts()
  const ids = { sel: useId(), name: useId() }
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const canCreate = allowCreate && can('action.accounts.edit')

  if (!q.data) return null
  const input = 'min-h-[44px] rounded-lg px-3 text-[16px] md:text-[14px] w-full min-w-0 focus-visible:outline focus-visible:outline-2'
  const style = { backgroundColor: theme.colors.surfaceAlt, border: `1px solid ${theme.colors.border}`, color: theme.colors.text, outlineColor: theme.colors.primary }

  const create = async () => {
    const n = name.trim()
    if (!n) return
    setBusy(true)
    setError(null)
    try {
      const acct = await accountsApi.create({ name: n })
      toast.show(fill(tha.created, { name: acct.name }), 'success', 2000)
      invalidate()
      onChange(acct.id)
      setCreating(false)
      setName('')
    } catch (e) {
      setError(trackerErrorText(e, t))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={`flex flex-col gap-1 min-w-0 text-[12px] ${className ?? ''}`} style={{ color: theme.colors.textSub }}>
      <label htmlFor={ids.sel}>{label ?? tha.account}</label>
      <select id={ids.sel} value={creating ? NEW : value} className={input} style={style}
        onChange={(e) => {
          if (e.target.value === NEW) { setCreating(true); setError(null) } else { setCreating(false); onChange(e.target.value) }
        }}>
        <option value="">{tha.noAccount}</option>
        {q.data.items.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
        {canCreate && <option value={NEW}>{tha.addAccount}</option>}
      </select>
      {creating && (
        <div className="flex flex-col gap-1 mt-1">
          <label htmlFor={ids.name}>{tha.newAccountName}</label>
          <div className="flex gap-2">
            <input id={ids.name} value={name} maxLength={60} autoFocus placeholder={tha.newAccountPlaceholder}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); create() } }}
              className={input} style={style} />
            <button type="button" onClick={create} disabled={busy || !name.trim()}
              className="min-h-[44px] px-3 rounded-lg text-[14px] font-semibold shrink-0 disabled:opacity-50 focus-visible:outline focus-visible:outline-2"
              style={{ backgroundColor: theme.colors.primary, color: theme.colors.surface, outlineColor: theme.colors.primary }}>
              {busy ? tha.creating : tha.createAccount}
            </button>
          </div>
          {error && <p role="alert" className="text-[12px]" style={{ color: theme.colors.down }}>{error}</p>}
        </div>
      )}
    </div>
  )
}
