'use client'

import { memo, useId, useMemo, useState } from 'react'
import Link from 'next/link'
import { useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronUp, ExternalLink, Pencil, Trash2 } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useToast } from '@/hooks/useToast'
import { holdingsApi } from '@/lib/api'
import { checkHref } from '@/lib/check'
import { DASH, fill, shortDate } from '@/lib/insights'
import { HOLDINGS_KEY, toHoldingsError } from '@/hooks/useHoldings'
import {
  errorText, holdingChips, money, num, pct, spct, useToneColor, verdictTone, type Chip,
} from './format'
import type { Holding, HoldingAccount } from '@/types/holdings'

const ACCOUNTS: (HoldingAccount | '')[] = ['', 'TFSA', 'RRSP', 'FHSA', 'NON_REGISTERED', 'OTHER']

export function ChipList({ chips }: { chips: Chip[] }) {
  const theme = useTheme()
  const tone = useToneColor()
  const t = useI18nStore((s) => s.t)
  if (!chips.length) return null
  return (
    <ul className="flex flex-wrap gap-1.5" aria-label={t.holdings.list.status}>
      {chips.map((c) => {
        const color = tone(c.tone)
        return (
          <li key={c.key} title={c.title}
            className="text-[12px] font-medium px-2 py-0.5 rounded-full whitespace-nowrap"
            style={{ backgroundColor: c.tone === 'neutral' ? theme.colors.surfaceAlt : color + '1A', color }}>
            {c.label}
          </li>
        )
      })}
    </ul>
  )
}

function changeColor(v: number | null | undefined, up: string, down: string, flat: string) {
  if (v === null || v === undefined || !Number.isFinite(v) || v === 0) return flat
  return v > 0 ? up : down
}

interface ItemProps {
  h: Holding
  maxWeight: number
  reviewing: boolean
  reviewBusy: boolean
  onReview: (id: string) => void
}

function VerdictChip({ h }: { h: Holding }) {
  const t = useI18nStore((s) => s.t)
  const theme = useTheme()
  const tone = useToneColor()
  const v = h.last_review?.verdict ?? null
  const color = tone(verdictTone(v))
  return (
    <span className="text-[12px] font-semibold px-2 py-0.5 rounded-full whitespace-nowrap"
      style={{ backgroundColor: v ? color + '1A' : theme.colors.surfaceAlt, color }}
      title={v ? t.check.long.verdict[v] : undefined}>
      {v ? t.holdings.verdictShort[v] : t.holdings.chips.notReviewed}
    </span>
  )
}

function Actions({ h, reviewing, reviewBusy, onReview, onEdit, editing, compact }: ItemProps & {
  onEdit: () => void
  editing: boolean
  compact?: boolean
}) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const th = t.holdings
  const toast = useToast()
  const qc = useQueryClient()
  const [removing, setRemoving] = useState(false)
  const btn = 'min-h-[44px] min-w-[44px] px-3 rounded-lg text-[13px] font-medium flex items-center justify-center gap-1.5 focus-visible:outline focus-visible:outline-2 disabled:opacity-50'
  const style = { backgroundColor: theme.colors.surfaceAlt, color: theme.colors.text, outlineColor: theme.colors.primary }

  const remove = async () => {
    if (!window.confirm(fill(th.actions.confirmRemove, { symbol: h.symbol }))) return
    setRemoving(true)
    try {
      await holdingsApi.remove(h.id)
      qc.invalidateQueries({ queryKey: HOLDINGS_KEY })
    } catch (e) {
      toast.show(errorText(toHoldingsError(e).code, th), 'error')
      setRemoving(false)
    }
  }

  return (
    <div className="flex flex-wrap gap-1.5">
      <button type="button" className={btn} style={{ ...style, color: theme.colors.primary }}
        disabled={reviewBusy} onClick={() => onReview(h.id)}
        aria-label={`${h.last_review ? th.actions.reReview : th.actions.review} ${h.symbol}`}>
        {reviewing ? th.actions.reviewing : h.last_review ? th.actions.reReview : th.actions.review}
      </button>
      <Link href={checkHref(h.symbol, 'long')} className={btn} style={style}
        aria-label={`${th.actions.checkLong} ${h.symbol}`}>
        {!compact && th.actions.checkLong}
        <ExternalLink size={14} aria-hidden="true" />
      </Link>
      <Link href={`/signals/${encodeURIComponent(h.symbol)}`} className={btn} style={style}
        aria-label={`${th.actions.signals} ${h.symbol}`}>
        {th.actions.signals}
      </Link>
      <button type="button" className={btn} style={style} onClick={onEdit} aria-expanded={editing}
        aria-label={fill(th.edit.title, { symbol: h.symbol })}>
        <Pencil size={14} aria-hidden="true" />{!compact && th.actions.edit}
      </button>
      <button type="button" className={btn} style={{ ...style, color: theme.colors.down }} onClick={remove}
        disabled={removing} aria-label={`${th.actions.remove} ${h.symbol}`}>
        <Trash2 size={14} aria-hidden="true" />
      </button>
    </div>
  )
}

function HoldingEditor({ h, onClose }: { h: Holding; onClose: () => void }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const th = t.holdings
  const toast = useToast()
  const qc = useQueryClient()
  const ids = { s: useId(), c: useId(), a: useId(), n: useId() }
  const [shares, setShares] = useState(h.shares != null ? String(h.shares) : '')
  const [cost, setCost] = useState(h.avg_cost != null ? String(h.avg_cost) : '')
  const [account, setAccount] = useState<HoldingAccount | ''>(h.account ?? '')
  const [notes, setNotes] = useState(h.notes ?? '')
  const [saving, setSaving] = useState(false)
  const parse = (v: string): number | null | 'bad' => {
    const s = v.trim().replace(',', '.')
    if (!s) return null
    const n = Number(s)
    return Number.isFinite(n) && n > 0 ? n : 'bad'
  }
  const ps = parse(shares)
  const pc = parse(cost)
  const bad = ps === 'bad' || pc === 'bad'
  const ccy = h.currency ?? (h.symbol.endsWith('.TO') ? 'CAD' : 'USD')
  const input = 'min-h-[44px] rounded-lg px-2 text-[16px] md:text-[14px] w-full min-w-0 focus-visible:outline focus-visible:outline-2'
  const style = { backgroundColor: theme.colors.surfaceAlt, border: `1px solid ${theme.colors.border}`, color: theme.colors.text, outlineColor: theme.colors.primary }

  const save = async (e: React.FormEvent) => {
    e.preventDefault()
    if (bad) return
    setSaving(true)
    try {
      await holdingsApi.update(h.id, {
        shares: ps as number | null, avg_cost: pc as number | null,
        account: account || null, notes: notes.trim() || null,
      })
      qc.invalidateQueries({ queryKey: HOLDINGS_KEY })
      onClose()
    } catch (err) {
      toast.show(errorText(toHoldingsError(err).code, th), 'error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={save} className="rounded-xl p-3 flex flex-col gap-3" style={{ border: `1px solid ${theme.colors.border}` }}
      aria-label={fill(th.edit.title, { symbol: h.symbol })}>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <label htmlFor={ids.s} className="flex flex-col gap-1 min-w-0 text-[12px]" style={{ color: theme.colors.textSub }}>
          {th.edit.shares}
          <input id={ids.s} inputMode="decimal" value={shares} onChange={(e) => setShares(e.target.value)} className={input}
            style={{ ...style, borderColor: ps === 'bad' ? theme.colors.down : theme.colors.border }} aria-invalid={ps === 'bad' || undefined} />
        </label>
        <label htmlFor={ids.c} className="flex flex-col gap-1 min-w-0 text-[12px]" style={{ color: theme.colors.textSub }}>
          {fill(th.edit.avgCost, { ccy })}
          <input id={ids.c} inputMode="decimal" value={cost} onChange={(e) => setCost(e.target.value)} className={input}
            style={{ ...style, borderColor: pc === 'bad' ? theme.colors.down : theme.colors.border }} aria-invalid={pc === 'bad' || undefined} />
        </label>
        <label htmlFor={ids.a} className="col-span-2 sm:col-span-1 flex flex-col gap-1 min-w-0 text-[12px]" style={{ color: theme.colors.textSub }}>
          {th.edit.account}
          <select id={ids.a} value={account} onChange={(e) => setAccount(e.target.value as HoldingAccount | '')} className={input} style={style}>
            {ACCOUNTS.map((a) => (
              <option key={a || 'none'} value={a}>{a ? th.edit.accounts[a] : th.edit.accounts.none}</option>
            ))}
          </select>
        </label>
        <label htmlFor={ids.n} className="col-span-2 sm:col-span-1 flex flex-col gap-1 min-w-0 text-[12px]" style={{ color: theme.colors.textSub }}>
          {th.edit.notes}
          <input id={ids.n} value={notes} maxLength={500} onChange={(e) => setNotes(e.target.value)} className={input} style={style} />
        </label>
      </div>
      {bad && <p role="alert" className="text-[12px]" style={{ color: theme.colors.down }}>{th.edit.invalid}</p>}
      <div className="flex gap-2">
        <button type="submit" disabled={bad || saving}
          className="min-h-[44px] px-4 rounded-lg text-[14px] font-semibold disabled:opacity-50 focus-visible:outline focus-visible:outline-2"
          style={{ backgroundColor: theme.colors.primary, color: theme.colors.surface, outlineColor: theme.colors.primary }}>
          {th.actions.save}
        </button>
        <button type="button" onClick={onClose}
          className="min-h-[44px] px-4 rounded-lg text-[14px] font-medium focus-visible:outline focus-visible:outline-2"
          style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.text, outlineColor: theme.colors.primary }}>
          {th.actions.cancel}
        </button>
      </div>
    </form>
  )
}

function ReviewDetails({ h }: { h: Holding }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const th = t.holdings
  const r = h.last_review
  const flags = h.holding_status?.red_flags ?? []
  if (!r && !flags.length) return null
  return (
    <div className="text-[13px] flex flex-col gap-1.5 min-w-0" style={{ color: theme.colors.textSub }}>
      {r?.key_concern && (
        <p className="min-w-0 break-words">
          <span className="font-medium" style={{ color: theme.colors.text }}>{th.actions.keyConcern}: </span>
          {r.key_concern}
        </p>
      )}
      {flags.map((f) => (
        <p key={f.key ?? f.text} className="min-w-0 break-words" style={{ color: theme.colors.down }}>
          🚩 {f.text}{' '}
          {f.url && /^https?:\/\//.test(f.url) && (
            <a href={f.url} target="_blank" rel="noopener noreferrer" className="underline">{th.actions.source}</a>
          )}
        </p>
      ))}
      {r?.reviewed_at && <p className="text-[12px]">{fill(th.actions.reviewedOn, { date: shortDate(r.reviewed_at, locale, true) })}</p>}
    </div>
  )
}

function PositionLine({ h }: { h: Holding }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const th = t.holdings
  const p = h.position
  if (!h.shares) return <p className="text-[12px]" style={{ color: theme.colors.textHint }}>{th.list.noShares}</p>
  const ccy = h.currency ?? p?.currency ?? 'USD'
  return (
    <p className="text-[12px] tabular-nums flex flex-wrap gap-x-3 gap-y-0.5" style={{ color: theme.colors.textSub }}>
      <span>{fill(th.list.shares, { n: num(h.shares, locale) })}{h.avg_cost ? ` · ${fill(th.list.avgCost, { cost: money(h.avg_cost, ccy, locale) })}` : ''}</span>
      {p?.value != null && <span>{th.list.value}: {money(p.value, ccy, locale)}{ccy !== 'CAD' && p.value_cad != null ? ` (${money(p.value_cad, 'CAD', locale, 0)})` : ''}</span>}
      {p?.unrealized != null && (
        <span style={{ color: changeColor(p.unrealized, theme.colors.up, theme.colors.down, theme.colors.textSub) }}>
          {th.list.gain}: {money(p.unrealized, ccy, locale)} ({spct(p.unrealized_pct, 1)})
        </span>
      )}
      {p?.weight_pct != null && (
        <span style={{ color: p.overweight ? theme.colors.down : theme.colors.textSub }}>{th.list.weight}: {pct(p.weight_pct, 1)}</span>
      )}
    </p>
  )
}

const HoldingCard = memo(function HoldingCard(props: ItemProps) {
  const { h, maxWeight } = props
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const th = t.holdings
  const [editing, setEditing] = useState(false)
  const [open, setOpen] = useState(false)
  const st = h.holding_status || {}
  const chips = useMemo(() => holdingChips(h, th, maxWeight), [h, th, maxWeight])
  const ccy = h.currency ?? 'USD'
  const hasDetails = !!(h.last_review?.key_concern || st.red_flags?.length)
  return (
    <li className="rounded-2xl p-4 flex flex-col gap-2.5 min-w-0"
      style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.border}` }}>
      <div className="flex items-start justify-between gap-3 min-w-0">
        <div className="min-w-0">
          <h3 className="font-mono font-semibold text-[16px]" style={{ color: theme.colors.text }}>{h.symbol}</h3>
          <p className="text-[12px] truncate" style={{ color: theme.colors.textSub }}>
            {h.name ?? DASH}{h.exchange ? ` · ${h.exchange}` : ''}
          </p>
        </div>
        <div className="text-right shrink-0">
          <p className="text-[15px] font-semibold tabular-nums" style={{ color: theme.colors.text }}>
            {st.price != null ? money(st.price, ccy, locale) : DASH}
          </p>
          <p className="text-[12px] tabular-nums" style={{ color: changeColor(st.day_change_pct, theme.colors.up, theme.colors.down, theme.colors.textSub) }}>
            {th.list.day} {spct(st.day_change_pct, 2)}
          </p>
        </div>
      </div>
      <p className="text-[12px] tabular-nums flex flex-wrap gap-x-3" style={{ color: theme.colors.textSub }}>
        <span>{th.list.m1} <span style={{ color: changeColor(st.change_1m_pct, theme.colors.up, theme.colors.down, theme.colors.textSub) }}>{spct(st.change_1m_pct, 1)}</span></span>
        <span>{th.list.ytd} <span style={{ color: changeColor(st.ytd_pct, theme.colors.up, theme.colors.down, theme.colors.textSub) }}>{spct(st.ytd_pct, 1)}</span></span>
        {st.drawdown_pct != null && <span>{fill(th.chips.drawdown, { pct: spct(st.drawdown_pct, 0) })}</span>}
        {st.stale && <span style={{ color: theme.colors.warning }}>{th.list.stale}</span>}
      </p>
      <div className="flex flex-wrap items-center gap-1.5">
        <VerdictChip h={h} />
        <ChipList chips={chips} />
      </div>
      <PositionLine h={h} />
      {hasDetails && (
        <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}
          className="self-start min-h-[44px] text-[13px] font-medium flex items-center gap-1 focus-visible:outline focus-visible:outline-2"
          style={{ color: theme.colors.primary, outlineColor: theme.colors.primary }}>
          {open ? th.actions.less : fill(th.actions.more, { symbol: h.symbol })}
          {open ? <ChevronUp size={14} aria-hidden="true" /> : <ChevronDown size={14} aria-hidden="true" />}
        </button>
      )}
      {open && <ReviewDetails h={h} />}
      <Actions {...props} onEdit={() => setEditing((e) => !e)} editing={editing} compact />
      {editing && <HoldingEditor h={h} onClose={() => setEditing(false)} />}
    </li>
  )
})

const HoldingRow = memo(function HoldingRow(props: ItemProps) {
  const { h, maxWeight } = props
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const th = t.holdings
  const [editing, setEditing] = useState(false)
  const st = h.holding_status || {}
  const chips = useMemo(() => holdingChips(h, th, maxWeight), [h, th, maxWeight])
  const ccy = h.currency ?? 'USD'
  const td = 'px-3 py-3 align-top'
  return (
    <>
      <tr style={{ borderTop: `1px solid ${theme.colors.border}` }}>
        <th scope="row" className={`${td} text-left font-normal`}>
          <p className="font-mono font-semibold text-[14px]" style={{ color: theme.colors.text }}>{h.symbol}</p>
          <p className="text-[12px] max-w-[220px] truncate" style={{ color: theme.colors.textSub }} title={h.name ?? undefined}>{h.name ?? DASH}</p>
        </th>
        <td className={`${td} text-right tabular-nums`}>
          <p className="text-[14px]" style={{ color: theme.colors.text }}>{st.price != null ? money(st.price, ccy, locale) : DASH}</p>
          <p className="text-[12px]" style={{ color: changeColor(st.day_change_pct, theme.colors.up, theme.colors.down, theme.colors.textSub) }}>{spct(st.day_change_pct, 2)}</p>
        </td>
        <td className={`${td} text-right tabular-nums text-[13px]`} style={{ color: changeColor(st.change_1m_pct, theme.colors.up, theme.colors.down, theme.colors.textSub) }}>{spct(st.change_1m_pct, 1)}</td>
        <td className={`${td} text-right tabular-nums text-[13px]`} style={{ color: changeColor(st.ytd_pct, theme.colors.up, theme.colors.down, theme.colors.textSub) }}>{spct(st.ytd_pct, 1)}</td>
        <td className={td}>
          <ChipList chips={chips} />
          {st.drawdown_pct != null && (
            <p className="text-[12px] mt-1 tabular-nums" style={{ color: theme.colors.textSub }}>{fill(th.chips.drawdown, { pct: spct(st.drawdown_pct, 0) })}</p>
          )}
        </td>
        <td className={`${td} text-right tabular-nums text-[13px]`}>
          {h.position?.weight_pct != null ? (
            <span style={{ color: h.position.overweight ? theme.colors.down : theme.colors.text }}>{pct(h.position.weight_pct, 1)}</span>
          ) : <span style={{ color: theme.colors.textHint }}>{DASH}</span>}
          {h.position?.unrealized_pct != null && (
            <p className="text-[12px]" style={{ color: changeColor(h.position.unrealized_pct, theme.colors.up, theme.colors.down, theme.colors.textSub) }}>{spct(h.position.unrealized_pct, 1)}</p>
          )}
        </td>
        <td className={td}>
          <VerdictChip h={h} />
          {h.last_review?.key_concern && (
            <p className="text-[12px] mt-1 max-w-[240px] line-clamp-2" style={{ color: theme.colors.textSub }} title={h.last_review.key_concern}>{h.last_review.key_concern}</p>
          )}
        </td>
        <td className={td}>
          <Actions {...props} onEdit={() => setEditing((e) => !e)} editing={editing} compact />
        </td>
      </tr>
      {editing && (
        <tr>
          <td colSpan={8} className="px-3 pb-3">
            <HoldingEditor h={h} onClose={() => setEditing(false)} />
          </td>
        </tr>
      )}
    </>
  )
})

export function HoldingsList({ items, maxWeight, reviewingId, reviewBusy, onReview }: {
  items: Holding[]
  maxWeight: number
  reviewingId: string | null
  reviewBusy: boolean
  onReview: (id: string) => void
}) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const th = t.holdings
  const thc = 'px-3 py-2 text-[12px] font-medium whitespace-nowrap'
  return (
    <>
      <ul className="flex flex-col gap-3 lg:hidden">
        {items.map((h) => (
          <HoldingCard key={h.id} h={h} maxWeight={maxWeight} reviewing={reviewingId === h.id}
            reviewBusy={reviewBusy} onReview={onReview} />
        ))}
      </ul>
      <div className="hidden lg:block rounded-2xl overflow-x-auto"
        style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.border}` }}>
        <table className="w-full text-left">
          <caption className="sr-only">{th.list.title}</caption>
          <thead>
            <tr style={{ color: theme.colors.textSub }}>
              <th scope="col" className={thc}>{th.list.symbol}</th>
              <th scope="col" className={`${thc} text-right`}>{th.list.price} / {th.list.day}</th>
              <th scope="col" className={`${thc} text-right`}>{th.list.m1}</th>
              <th scope="col" className={`${thc} text-right`}>{th.list.ytd}</th>
              <th scope="col" className={thc}>{th.list.status}</th>
              <th scope="col" className={`${thc} text-right`}>{th.list.weight} / {th.list.gain}</th>
              <th scope="col" className={thc}>{th.list.verdict}</th>
              <th scope="col" className={thc}>{th.list.actions}</th>
            </tr>
          </thead>
          <tbody>
            {items.map((h) => (
              <HoldingRow key={h.id} h={h} maxWeight={maxWeight} reviewing={reviewingId === h.id}
                reviewBusy={reviewBusy} onReview={onReview} />
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}
