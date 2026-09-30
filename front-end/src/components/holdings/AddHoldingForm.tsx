'use client'

import { useId, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { ClipboardList, Search, X } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useToast } from '@/hooks/useToast'
import { holdingsApi } from '@/lib/api'
import { fill } from '@/lib/insights'
import { HOLDINGS_KEY, toHoldingsError } from '@/hooks/useHoldings'
import { SymbolCombobox } from '@/components/check/SymbolCombobox'
import { errorText } from '@/components/holdings/format'
import { AccountSelect } from '@/components/holdings/AccountSelect'
import type { Holding, HoldingAssetType } from '@/types/holdings'
import type { SymbolMatch, SymbolType } from '@/types/symbols'

const ASSET_TYPE: Record<SymbolType, HoldingAssetType> = { stock: 'STOCK', etf: 'ETF', crypto: 'CRYPTO' }

function guessCurrency(symbol: string): string {
  if (symbol.endsWith('.TO') || symbol.endsWith('.V') || symbol.endsWith('-CAD')) return 'CAD'
  return 'USD'
}

/** Add one holding: search by name or ticker, pick a match, optionally
 *  enter shares / average cost / account, save. The bulk paste import is
 *  one click away (`onPasteList`). */
export function AddHoldingForm({ existing, defaultAccountId = '', onDone, onCancel, onPasteList }: {
  existing: Holding[]
  /** preselected account (e.g. the holdings page's account filter) */
  defaultAccountId?: string
  onDone: () => void
  onCancel?: () => void
  onPasteList: () => void
}) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const th = t.holdings
  const ta = th.add
  const toast = useToast()
  const qc = useQueryClient()
  const ids = { q: useId(), s: useId(), c: useId(), hint: useId() }

  const [query, setQuery] = useState('')
  const [picked, setPicked] = useState<SymbolMatch | null>(null)
  const [shares, setShares] = useState('')
  const [cost, setCost] = useState('')
  const [accountId, setAccountId] = useState(defaultAccountId)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const parse = (v: string): number | null | 'bad' => {
    const s = v.trim().replace(',', '.')
    if (!s) return null
    const n = Number(s)
    return Number.isFinite(n) && n > 0 ? n : 'bad'
  }
  const ps = parse(shares)
  const pc = parse(cost)
  const bad = ps === 'bad' || pc === 'bad'
  const ccy = picked ? guessCurrency(picked.symbol) : 'USD'
  const already = useMemo(
    () => (picked ? existing.some((h) => h.symbol === picked.symbol && (h.account_id ?? '') === accountId) : false),
    [picked, existing, accountId],
  )

  const input = 'min-h-[44px] rounded-lg px-3 text-[16px] md:text-[14px] w-full min-w-0 focus-visible:outline focus-visible:outline-2'
  const style = { backgroundColor: theme.colors.surfaceAlt, border: `1px solid ${theme.colors.border}`, color: theme.colors.text, outlineColor: theme.colors.primary }
  const label = 'flex flex-col gap-1 min-w-0 text-[12px]'

  const reset = () => {
    setPicked(null); setQuery(''); setShares(''); setCost(''); setAccountId(defaultAccountId); setError(null)
  }

  const save = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!picked || bad) return
    setSaving(true)
    setError(null)
    try {
      await holdingsApi.save([{
        symbol: picked.symbol,
        // what was typed may be a company name ("Enbridge"); the API wants a ticker here
        input_symbol: /^[A-Za-z0-9.\-]{1,24}$/.test(query.trim()) ? query.trim() : picked.symbol,
        name: picked.name,
        exchange: picked.exchange_label || picked.exchange,
        asset_type: ASSET_TYPE[picked.type] ?? 'OTHER',
        shares: ps as number | null,
        avg_cost: pc as number | null,
        account_id: accountId || null,
      }])
      toast.show(fill(ta.added, { symbol: picked.symbol }), 'success')
      qc.invalidateQueries({ queryKey: HOLDINGS_KEY })
      qc.invalidateQueries({ queryKey: ['auth', 'me'] }) // slot count
      reset()
      onDone()
    } catch (err) {
      const he = toHoldingsError(err)
      setError(errorText(he.code, th, { limit: he.limit ?? null }))
    } finally {
      setSaving(false)
    }
  }

  return (
    <section aria-labelledby={`${ids.q}-title`} className="rounded-2xl p-4 md:p-5 flex flex-col gap-4"
      style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.border}` }}>
      <div className="flex items-center justify-between gap-3">
        <h2 id={`${ids.q}-title`} className="text-[17px] font-semibold" style={{ color: theme.colors.text }}>{ta.title}</h2>
        <button type="button" onClick={onPasteList}
          className="min-h-[44px] px-3 rounded-lg text-[13px] font-medium flex items-center gap-1.5 focus-visible:outline focus-visible:outline-2"
          style={{ color: theme.colors.primary, outlineColor: theme.colors.primary }}>
          <ClipboardList size={15} aria-hidden="true" />{ta.pasteList}
        </button>
      </div>

      {!picked ? (
        <div className={label} style={{ color: theme.colors.textSub }}>
          <label htmlFor={ids.q}>{ta.search}</label>
          <div className="relative flex items-center gap-2 rounded-lg px-3" style={style}>
            <Search size={16} aria-hidden="true" style={{ color: theme.colors.textHint }} />
            <SymbolCombobox
              id={ids.q}
              value={query}
              onChange={setQuery}
              onPick={(m) => { setPicked(m); setError(null) }}
              placeholder={ta.searchPlaceholder}
              describedBy={ids.hint}
              ariaLabel={ta.search}
              className="bg-transparent outline-0 min-w-0 flex-1 h-11 text-[16px] md:text-[14px]"
            />
          </div>
        </div>
      ) : (
        <form onSubmit={save} className="flex flex-col gap-3" aria-label={ta.title}>
          <div className="flex items-center justify-between gap-3 rounded-xl px-3 py-2.5 min-w-0"
            style={{ backgroundColor: theme.colors.surfaceAlt }}>
            <div className="min-w-0">
              <p className="text-[15px] font-semibold truncate" style={{ color: theme.colors.text }}>
                {picked.symbol}
                <span className="ml-2 text-[12px] font-normal" style={{ color: theme.colors.textSub }}>{picked.exchange_label}</span>
              </p>
              {picked.name && <p className="text-[13px] truncate" style={{ color: theme.colors.textSub }}>{picked.name}</p>}
            </div>
            <button type="button" onClick={reset}
              className="min-h-[44px] px-3 rounded-lg text-[13px] font-medium flex items-center gap-1 shrink-0 focus-visible:outline focus-visible:outline-2"
              style={{ color: theme.colors.textSub, outlineColor: theme.colors.primary }}
              aria-label={`${ta.change} ${picked.symbol}`}>
              <X size={14} aria-hidden="true" />{ta.change}
            </button>
          </div>

          {already && <p className="text-[12px]" style={{ color: theme.colors.textSub }}>{fill(ta.already, { symbol: picked.symbol })}</p>}

          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            <label htmlFor={ids.s} className={label} style={{ color: theme.colors.textSub }}>
              {ta.sharesOptional}
              <input id={ids.s} inputMode="decimal" autoFocus value={shares} onChange={(e) => setShares(e.target.value)}
                className={input} style={{ ...style, borderColor: ps === 'bad' ? theme.colors.down : theme.colors.border }}
                aria-invalid={ps === 'bad' || undefined} />
            </label>
            <label htmlFor={ids.c} className={label} style={{ color: theme.colors.textSub }}>
              {fill(ta.costOptional, { ccy })}
              <input id={ids.c} inputMode="decimal" value={cost} onChange={(e) => setCost(e.target.value)}
                className={input} style={{ ...style, borderColor: pc === 'bad' ? theme.colors.down : theme.colors.border }}
                aria-invalid={pc === 'bad' || undefined} />
            </label>
            <AccountSelect className="col-span-2 sm:col-span-1" value={accountId} onChange={setAccountId} />
          </div>
          {bad && <p role="alert" className="text-[12px]" style={{ color: theme.colors.down }}>{th.edit.invalid}</p>}
          {error && <p role="alert" className="text-[13px]" style={{ color: theme.colors.down }}>{error}</p>}

          <div className="flex flex-wrap gap-2">
            <button type="submit" disabled={bad || saving}
              className="min-h-[44px] px-4 rounded-xl text-[14px] font-semibold disabled:opacity-50 focus-visible:outline focus-visible:outline-2"
              style={{ backgroundColor: theme.colors.primary, color: theme.colors.surface, outlineColor: theme.colors.primary }}>
              {saving ? ta.adding : ta.add}
            </button>
            {onCancel && (
              <button type="button" onClick={() => { reset(); onCancel() }}
                className="min-h-[44px] px-4 rounded-xl text-[14px] font-medium focus-visible:outline focus-visible:outline-2"
                style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.text, outlineColor: theme.colors.primary }}>
                {th.import.cancel}
              </button>
            )}
          </div>
        </form>
      )}

      <p id={ids.hint} className="text-[12px]" style={{ color: theme.colors.textHint }}>{ta.hint}</p>
      {!picked && onCancel && (
        <div>
          <button type="button" onClick={onCancel}
            className="min-h-[44px] px-4 rounded-xl text-[14px] font-medium focus-visible:outline focus-visible:outline-2"
            style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.text, outlineColor: theme.colors.primary }}>
            {th.import.cancel}
          </button>
        </div>
      )}
    </section>
  )
}
