'use client'

import { useId, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Search } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useToast } from '@/hooks/useToast'
import { holdingsApi } from '@/lib/api'
import { fill } from '@/lib/insights'
import { Panel } from '@/components/insights/Panel'
import { HOLDINGS_KEY, toHoldingsError } from '@/hooks/useHoldings'
import { errorText, money, useToneColor, type Tone } from './format'
import type { HoldingUpsertItem, Listing, ResolvedLine } from '@/types/holdings'

interface Row {
  line: ResolvedLine
  include: boolean
  symbol: string | null
  shares: string
  cost: string
}

function parsePositive(v: string): number | null | 'bad' {
  const s = v.trim().replace(',', '.')
  if (!s) return null
  const n = Number(s)
  return Number.isFinite(n) && n > 0 ? n : 'bad'
}

export function ImportPanel({ onDone, onCancel, showCancel }: {
  onDone: () => void
  onCancel?: () => void
  showCancel: boolean
}) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const th = t.holdings
  const toast = useToast()
  const qc = useQueryClient()
  const tone = useToneColor()
  const textId = useId()
  const hintId = useId()
  const [text, setText] = useState('')
  const [phase, setPhase] = useState<'edit' | 'resolving' | 'confirm' | 'saving'>('edit')
  const [rows, setRows] = useState<Row[]>([])
  const [error, setError] = useState<string | null>(null)

  const check = async () => {
    if (!text.trim()) return
    setError(null)
    setPhase('resolving')
    try {
      const res = await holdingsApi.resolve(text)
      setRows(res.lines.map((l) => ({
        line: l,
        include: l.status === 'ok' || l.status === 'ambiguous',
        symbol: l.selected?.symbol ?? null,
        shares: l.shares != null ? String(l.shares) : '',
        cost: l.avg_cost != null ? String(l.avg_cost) : '',
      })))
      setPhase('confirm')
    } catch (e) {
      const err = toHoldingsError(e)
      setError(errorText(err.code, th))
      setPhase('edit')
    }
  }

  const update = (i: number, patch: Partial<Row>) =>
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)))

  const selected = rows.filter((r) => r.include && r.symbol)
  const invalidNumbers = selected.some((r) => parsePositive(r.shares) === 'bad' || parsePositive(r.cost) === 'bad')

  const save = async () => {
    if (!selected.length || invalidNumbers) return
    setError(null)
    setPhase('saving')
    const items: HoldingUpsertItem[] = selected.map((r) => {
      const l = r.line.alternatives.find((a) => a.symbol === r.symbol) as Listing
      const shares = parsePositive(r.shares)
      const cost = parsePositive(r.cost)
      return {
        symbol: l.symbol,
        input_symbol: r.line.input,
        name: l.name,
        exchange: l.exchange,
        currency: l.currency,
        asset_type: l.asset_type,
        shares: typeof shares === 'number' ? shares : null,
        avg_cost: typeof cost === 'number' ? cost : null,
        account: r.line.account,
      }
    })
    try {
      const res = await holdingsApi.save(items)
      toast.show(fill(th.import.saved, { n: res.count }), 'success')
      qc.invalidateQueries({ queryKey: HOLDINGS_KEY })
      setText('')
      qc.invalidateQueries({ queryKey: ['auth', 'me'] }) // slot count
      setRows([])
      setPhase('edit')
      onDone()
    } catch (e) {
      const he = toHoldingsError(e)
      setError(errorText(he.code, th, { limit: he.limit ?? null }))
      setPhase('confirm')
    }
  }

  const counts = {
    ok: rows.filter((r) => r.line.status === 'ok').length,
    ambiguous: rows.filter((r) => r.line.status === 'ambiguous').length,
    missing: rows.filter((r) => r.line.status === 'not_found' || r.line.status === 'invalid').length,
  }

  const inputStyle = {
    backgroundColor: theme.colors.surfaceAlt,
    border: `1px solid ${theme.colors.border}`,
    color: theme.colors.text,
    outlineColor: theme.colors.primary,
  }
  const btn = 'min-h-[44px] px-4 rounded-xl text-[14px] font-semibold transition-opacity disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2'

  return (
    <Panel title={phase === 'confirm' || phase === 'saving' ? th.import.confirmTitle : th.import.title}
      subtitle={phase === 'confirm' || phase === 'saving' ? th.import.confirmHint : undefined}>
      {(phase === 'edit' || phase === 'resolving') && (
        <div className="flex flex-col gap-3">
          <label htmlFor={textId} className="text-[13px] font-medium" style={{ color: theme.colors.text }}>
            {th.import.label}
          </label>
          <textarea
            id={textId}
            aria-describedby={hintId}
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={8}
            spellCheck={false}
            autoCapitalize="characters"
            autoCorrect="off"
            placeholder={th.import.placeholder}
            disabled={phase === 'resolving'}
            className="w-full rounded-xl p-3 font-mono text-[16px] md:text-[14px] leading-relaxed focus-visible:outline focus-visible:outline-2"
            style={inputStyle}
          />
          <div id={hintId} className="text-[13px] flex flex-col gap-2" style={{ color: theme.colors.textSub }}>
            <p className="font-medium" style={{ color: theme.colors.text }}>{th.empty.formats}</p>
            <ul className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1">
              {th.empty.examples.map((ex) => (
                <li key={ex.code} className="min-w-0">
                  <code className="font-mono text-[12px] px-1.5 py-0.5 rounded" style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.text }}>{ex.code}</code>
                  <span className="ml-2">{ex.desc}</span>
                </li>
              ))}
            </ul>
            <p>{th.empty.suffixHint}</p>
          </div>
          {error && <p role="alert" className="text-[13px]" style={{ color: theme.colors.down }}>{error}</p>}
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={check} disabled={!text.trim() || phase === 'resolving'}
              className={`${btn} flex items-center gap-2`}
              style={{ backgroundColor: theme.colors.primary, color: theme.colors.surface, outlineColor: theme.colors.primary }}>
              <Search size={16} aria-hidden="true" />
              {phase === 'resolving' ? th.import.checking : th.import.check}
            </button>
            {showCancel && onCancel && (
              <button type="button" onClick={onCancel} disabled={phase === 'resolving'} className={btn}
                style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.text, outlineColor: theme.colors.primary }}>
                {th.import.cancel}
              </button>
            )}
          </div>
          {phase === 'resolving' && (
            <p role="status" className="text-[13px]" style={{ color: theme.colors.textSub }}>{th.import.checkingHint}</p>
          )}
        </div>
      )}

      {(phase === 'confirm' || phase === 'saving') && (
        <div className="flex flex-col gap-3">
          <p className="text-[13px]" style={{ color: theme.colors.textSub }}>
            {fill(th.import.summary, counts)}
          </p>
          <ul className="flex flex-col gap-2">
            {rows.map((r, i) => {
              const l = r.line
              const st: Tone = l.status === 'ok' ? 'up' : l.status === 'ambiguous' ? 'warning' : 'down'
              const cur = l.alternatives.find((a) => a.symbol === r.symbol) ?? null
              const usable = l.alternatives.length > 0
              const shareBad = parsePositive(r.shares) === 'bad'
              const costBad = parsePositive(r.cost) === 'bad'
              return (
                <li key={`${l.line}-${l.input}`} className="rounded-xl p-3 flex flex-col gap-2 min-w-0"
                  style={{ border: `1px solid ${theme.colors.border}`, backgroundColor: r.include ? 'transparent' : theme.colors.surfaceAlt }}>
                  <div className="flex items-start gap-3 min-w-0">
                    <label className="flex items-center justify-center min-w-[44px] min-h-[44px] -m-2 cursor-pointer">
                      <input type="checkbox" checked={r.include} disabled={!usable}
                        onChange={(e) => update(i, { include: e.target.checked })}
                        className="w-5 h-5" style={{ accentColor: theme.colors.primary }}
                        aria-label={fill(th.import.include, { symbol: l.input })} />
                    </label>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                        <span className="font-mono font-semibold text-[15px]" style={{ color: theme.colors.text }}>{l.input}</span>
                        {cur && <span className="text-[13px] truncate max-w-full" style={{ color: theme.colors.textSub }}>{cur.name}</span>}
                      </div>
                      <p className="text-[12px] mt-0.5" style={{ color: tone(st) }}>
                        {th.import.status[l.status]}
                        {l.note ? ` · ${th.import.notes[l.note]}` : ''}
                        {l.merged ? ` · ${fill(th.import.merged, { n: l.merged })}` : ''}
                      </p>
                      {l.existing && <p className="text-[12px]" style={{ color: theme.colors.textSub }}>{th.import.existing}</p>}
                    </div>
                    {cur && (
                      <span className="text-[13px] tabular-nums shrink-0 text-right" style={{ color: theme.colors.text }}>
                        <span className="sr-only">{th.import.price}: </span>{money(cur.price, cur.currency, locale)}
                      </span>
                    )}
                  </div>
                  {usable && (
                    <div className="grid grid-cols-2 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)] gap-2">
                      <label className="col-span-2 sm:col-span-1 flex flex-col gap-1 min-w-0">
                        <span className="text-[12px]" style={{ color: theme.colors.textSub }}>{th.import.listing}</span>
                        <select value={r.symbol ?? ''} onChange={(e) => update(i, { symbol: e.target.value })}
                          aria-label={fill(th.import.chooseListing, { symbol: l.input })}
                          className="min-h-[44px] rounded-lg px-2 text-[16px] md:text-[14px] w-full min-w-0 focus-visible:outline focus-visible:outline-2"
                          style={inputStyle}>
                          {l.alternatives.map((a) => (
                            <option key={a.symbol} value={a.symbol}>
                              {a.symbol} — {a.name ?? '?'} ({a.exchange}, {a.currency})
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="flex flex-col gap-1 min-w-0">
                        <span className="text-[12px]" style={{ color: theme.colors.textSub }}>{th.import.shares}</span>
                        <input inputMode="decimal" value={r.shares} onChange={(e) => update(i, { shares: e.target.value })}
                          aria-invalid={shareBad || undefined}
                          className="min-h-[44px] rounded-lg px-2 text-[16px] md:text-[14px] w-full min-w-0 tabular-nums focus-visible:outline focus-visible:outline-2"
                          style={{ ...inputStyle, borderColor: shareBad ? theme.colors.down : theme.colors.border }} />
                      </label>
                      <label className="flex flex-col gap-1 min-w-0">
                        <span className="text-[12px]" style={{ color: theme.colors.textSub }}>
                          {th.import.cost}{cur ? ` (${cur.currency})` : ''}
                        </span>
                        <input inputMode="decimal" value={r.cost} onChange={(e) => update(i, { cost: e.target.value })}
                          aria-invalid={costBad || undefined}
                          className="min-h-[44px] rounded-lg px-2 text-[16px] md:text-[14px] w-full min-w-0 tabular-nums focus-visible:outline focus-visible:outline-2"
                          style={{ ...inputStyle, borderColor: costBad ? theme.colors.down : theme.colors.border }} />
                      </label>
                    </div>
                  )}
                </li>
              )
            })}
          </ul>
          {invalidNumbers && <p role="alert" className="text-[13px]" style={{ color: theme.colors.down }}>{th.edit.invalid}</p>}
          {error && <p role="alert" className="text-[13px]" style={{ color: theme.colors.down }}>{error}</p>}
          <div className="flex flex-wrap gap-2 sticky bottom-[76px] md:bottom-2 py-2" style={{ backgroundColor: theme.colors.surface }}>
            <button type="button" onClick={save} disabled={!selected.length || invalidNumbers || phase === 'saving'} className={btn}
              style={{ backgroundColor: theme.colors.primary, color: theme.colors.surface, outlineColor: theme.colors.primary }}>
              {phase === 'saving' ? th.import.saving : selected.length ? fill(th.import.save, { n: selected.length }) : th.import.none}
            </button>
            <button type="button" onClick={() => setPhase('edit')} disabled={phase === 'saving'} className={btn}
              style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.text, outlineColor: theme.colors.primary }}>
              {th.import.back}
            </button>
          </div>
        </div>
      )}
    </Panel>
  )
}
