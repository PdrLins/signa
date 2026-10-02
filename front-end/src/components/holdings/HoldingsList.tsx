'use client'

import { memo, useId, useMemo, useState } from 'react'
import Link from 'next/link'
import { useQueryClient } from '@tanstack/react-query'
import { Activity, ArrowLeftRight, Bell, ExternalLink, FileText, Pencil, Sparkles, Trash2 } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useCardLink } from '@/hooks/useCardLink'
import { useAccess } from '@/hooks/useAccess'
import { useToast } from '@/hooks/useToast'
import { holdingsApi } from '@/lib/api'
import { checkHref } from '@/lib/check'
import { DASH, fill, shortDate } from '@/lib/insights'
import { HOLDINGS_KEY, toHoldingsError } from '@/hooks/useHoldings'
import {
  errorText, holdingChips, money, num, pct, spct, useMaskedMoney, useToneColor, verdictTone, type Chip,
} from './format'
import { AccountSelect } from '@/components/holdings/AccountSelect'
import { ActionMenu, type ActionMenuItem } from '@/components/ui/ActionMenu'
import type { Holding } from '@/types/holdings'

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

/** Everything a holding can do, behind one "⋯" button (the row itself opens
 *  the stock page). Owner-only AI items only appear for the owner. */
function RowMenu({ h, reviewing, reviewBusy, onReview, onEdit, onToggleNotes, hasNotes }: ItemProps & {
  onEdit: () => void
  onToggleNotes: () => void
  hasNotes: boolean
}) {
  const t = useI18nStore((s) => s.t)
  const th = t.holdings
  const toast = useToast()
  const qc = useQueryClient()
  const [removing, setRemoving] = useState(false)
  const { can } = useAccess()
  const sym = encodeURIComponent(h.symbol)

  const remove = async () => {
    if (!window.confirm(fill(th.actions.confirmRemove, { symbol: h.symbol }))) return
    setRemoving(true)
    try {
      await holdingsApi.remove(h.id)
      qc.invalidateQueries({ queryKey: HOLDINGS_KEY })
      qc.invalidateQueries({ queryKey: ['auth', 'me'] }) // slot count
      qc.invalidateQueries({ queryKey: ['following'] })
    } catch (e) {
      toast.show(errorText(toHoldingsError(e).code, th), 'error')
      setRemoving(false)
    }
  }

  const items: ActionMenuItem[] = [
    ...(can('action.holdings.edit') ? [{ key: 'edit', label: th.menu.edit, icon: Pencil, onSelect: onEdit }] : []),
    ...(can('action.transactions.edit') ? [{ key: 'trade', label: th.menu.trade, icon: ArrowLeftRight, href: `/profile/transactions?add=1&symbol=${sym}` }] : []),
    ...(can('area.stock') ? [{ key: 'alert', label: th.menu.alert, icon: Bell, href: `/stocks/${sym}?alert=1` }] : []),
    ...(can('action.holdings.review') ? [{
      key: 'review', label: reviewing ? th.actions.reviewing : h.last_review ? th.actions.reReview : th.actions.review,
      icon: Sparkles, onSelect: () => onReview(h.id), disabled: reviewBusy,
    }] : []),
    ...(hasNotes ? [{ key: 'notes', label: fill(th.actions.more, { symbol: h.symbol }), icon: FileText, onSelect: onToggleNotes }] : []),
    ...(can('area.check') ? [{ key: 'check', label: th.actions.checkLong, icon: ExternalLink, href: checkHref(h.symbol, 'long') }] : []),
    ...(can('area.signals') ? [{ key: 'signals', label: th.actions.signals, icon: Activity, href: `/signals/${sym}` }] : []),
    ...(can('action.holdings.edit') ? [{ key: 'remove', label: th.actions.remove, icon: Trash2, onSelect: remove, danger: true, disabled: removing }] : []),
  ]
  return <ActionMenu items={items} label={fill(th.menu.label, { symbol: h.symbol })} />
}

function HoldingEditor({ h, onClose }: { h: Holding; onClose: () => void }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const th = t.holdings
  const toast = useToast()
  const qc = useQueryClient()
  const ids = { s: useId(), c: useId(), n: useId() }
  const [shares, setShares] = useState(h.shares != null ? String(h.shares) : '')
  const [cost, setCost] = useState(h.avg_cost != null ? String(h.avg_cost) : '')
  const [accountId, setAccountId] = useState(h.account_id ?? '')
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
        notes: notes.trim() || null,
        // only send account_id when it changed (a move; 503 before migration 013)
        ...(accountId !== (h.account_id ?? '') ? { account_id: accountId || null } : {}),
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
        <AccountSelect className="col-span-2 sm:col-span-1" value={accountId} onChange={setAccountId} allowCreate={false} />
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

/** Price + day move for a row: the shared live quote (same price as the
 *  portfolio summary), else the monitor's last close. A move is labelled
 *  "today" only when the quote is live; otherwise it's the last session's,
 *  or nothing ("At last close"). */
export function rowPrice(h: Holding) {
  const st = h.holding_status || {}
  const q = h.quote ?? null
  const price = q?.price ?? st.price ?? null
  const live = !!q?.live
  const dayPct = live ? q?.change_pct ?? null : st.day_change_pct ?? null
  const dayAbs = live && q?.change != null && h.shares ? q.change * h.shares : null
  const ytd = q?.ytd_pct_live ?? st.ytd_pct ?? null
  return { price, live, dayPct, dayAbs, ytd }
}

/** "+0.94% today", "−0.3% last session" or "At last close". */
const DayMove = memo(function DayMove({ h, ccy, withAmount, className }: {
  h: Holding; ccy: string; withAmount?: boolean; className?: string
}) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const th = t.holdings
  const mm = useMaskedMoney()
  const { live, dayPct, dayAbs } = rowPrice(h)
  if (dayPct == null) {
    return <p className={className} style={{ color: theme.colors.textHint }}>{th.list.atLastClose}</p>
  }
  const color = changeColor(dayPct, theme.colors.up, theme.colors.down, theme.colors.textSub)
  return (
    <p className={className} style={{ color }}>
      {withAmount && dayAbs != null && <>{dayAbs >= 0 ? '+' : '−'}{mm(Math.abs(dayAbs), ccy, locale)} </>}
      {spct(dayPct, 2)}{' '}
      <span className="font-normal" style={{ color: theme.colors.textHint }}>{live ? th.list.today : th.list.lastSession}</span>
    </p>
  )
})

/** ETF / Stock / Crypto label (ETFs tinted). */
export const AssetBadge = memo(function AssetBadge({ type }: { type: string | null | undefined }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const k = String(type || '').toLowerCase()
  if (!['etf', 'stock', 'crypto'].includes(k)) return null
  const label = (t.stock.assetTypes as Record<string, string>)[k] ?? k
  const etf = k === 'etf'
  return (
    <span className="inline-block align-middle text-[10px] font-semibold uppercase tracking-wide px-1.5 py-px rounded"
      style={{ backgroundColor: etf ? theme.colors.primary + '22' : theme.colors.surfaceAlt, color: etf ? theme.colors.primary : theme.colors.textSub }}>
      {label}
    </span>
  )
})

/** The list hides chips that say "all fine" (trend OK / unknown): only what needs a look. */
function useListChips(h: Holding, maxWeight: number): Chip[] {
  const t = useI18nStore((s) => s.t)
  return useMemo(
    () => holdingChips(h, t.holdings, maxWeight).filter((c) => !(c.key === 'trend' && (c.tone === 'up' || c.tone === 'neutral'))),
    [h, t, maxWeight],
  )
}

const HoldingCard = memo(function HoldingCard(props: ItemProps) {
  const { h, maxWeight } = props
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const th = t.holdings
  const mm = useMaskedMoney()
  const [editing, setEditing] = useState(false)
  const [open, setOpen] = useState(false)
  const st = h.holding_status || {}
  const p = h.position
  const chips = useListChips(h, maxWeight)
  const ccy = h.currency ?? p?.currency ?? 'USD'
  const hasNotes = !!(h.last_review?.key_concern || st.red_flags?.length)
  const cardLink = useCardLink(`/stocks/${encodeURIComponent(h.symbol)}`)
  const hasValue = p?.value != null
  const { price } = rowPrice(h)
  return (
    <li onClick={cardLink.onClick} className={`rounded-2xl pl-4 pr-1 py-3 flex flex-col gap-1.5 min-w-0 hover:brightness-110 ${cardLink.className}`}
      style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.border}` }}>
      <div className="flex items-center gap-2 min-w-0">
        <div className="min-w-0 flex-1">
          <h3 className="font-mono font-semibold text-[15px] leading-tight flex items-center gap-1.5">
            <Link href={`/stocks/${encodeURIComponent(h.symbol)}`} className="focus-visible:outline focus-visible:outline-2 rounded"
              style={{ color: theme.colors.text, outlineColor: theme.colors.primary }} aria-label={fill(t.stock.openPage, { symbol: h.symbol })}>
              {h.symbol}
            </Link>
            <AssetBadge type={h.asset_type} />
          </h3>
          <p className="text-[12px] truncate" style={{ color: theme.colors.textSub }}>
            {h.name ?? DASH}{h.account_name ? ` · ${h.account_name}` : ''}
          </p>
        </div>
        <div className="text-right shrink-0 tabular-nums">
          <p className="text-[15px] font-semibold" style={{ color: theme.colors.text }}>
            {hasValue ? mm(p!.value, ccy, locale) : price != null ? money(price, ccy, locale) : DASH}
          </p>
          {hasValue && ccy !== 'CAD' && p!.value_cad != null && (
            <p className="text-[11.5px]" style={{ color: theme.colors.textHint }}>≈ {mm(p!.value_cad, 'CAD', locale, 0)}</p>
          )}
          <DayMove h={h} ccy={ccy} className="text-[12.5px] font-medium" />
        </div>
        <RowMenu {...props} onEdit={() => setEditing((e) => !e)} onToggleNotes={() => setOpen((o) => !o)} hasNotes={hasNotes} />
      </div>
      <p className="text-[12px] tabular-nums flex flex-wrap gap-x-3 gap-y-0.5 pr-3" style={{ color: theme.colors.textSub }}>
        {h.shares ? <span>{fill(h.shares === 1 ? th.list.shareOne : th.list.shares, { n: num(h.shares, locale) })} · {price != null ? money(price, ccy, locale) : DASH}</span>
          : <span style={{ color: theme.colors.textHint }}>{th.list.noShares}</span>}
        {p?.unrealized != null && (
          <span style={{ color: changeColor(p.unrealized, theme.colors.up, theme.colors.down, theme.colors.textSub) }}>
            {th.list.gain} {mm(p.unrealized, ccy, locale)} ({spct(p.unrealized_pct, 1)})
          </span>
        )}
        {p?.weight_pct != null && (
          <span style={{ color: p.overweight ? theme.colors.down : theme.colors.textSub }}>{pct(p.weight_pct, 1)}</span>
        )}
      </p>
      {(chips.length > 0 || h.last_review) && (
        <div className="flex flex-wrap items-center gap-1.5 pr-3">
          {h.last_review && <VerdictChip h={h} />}
          <ChipList chips={chips} />
        </div>
      )}
      {open && <div className="pr-3"><ReviewDetails h={h} /></div>}
      {editing && <div className="pr-3"><HoldingEditor h={h} onClose={() => setEditing(false)} /></div>}
    </li>
  )
})

const HoldingRow = memo(function HoldingRow(props: ItemProps & { showVerdict: boolean }) {
  const { h, maxWeight, showVerdict } = props
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const th = t.holdings
  const mm = useMaskedMoney()
  const [editing, setEditing] = useState(false)
  const [open, setOpen] = useState(false)
  const st = h.holding_status || {}
  const p = h.position
  const chips = useListChips(h, maxWeight)
  const ccy = h.currency ?? p?.currency ?? 'USD'
  const hasNotes = !!(h.last_review?.key_concern || st.red_flags?.length)
  const { price, ytd } = rowPrice(h)
  const td = 'px-3 py-2.5 align-middle'
  const rowLink = useCardLink(`/stocks/${encodeURIComponent(h.symbol)}`)
  const cols = showVerdict ? 10 : 9
  return (
    <>
      <tr onClick={rowLink.onClick} className={`hover:brightness-110 ${rowLink.className}`}
        style={{ borderTop: `1px solid ${theme.colors.border}`, backgroundColor: theme.colors.surface }}>
        <th scope="row" className={`${td} text-left font-normal`}>
          <p className="font-mono font-semibold text-[14px] flex items-center gap-1.5">
            <Link href={`/stocks/${encodeURIComponent(h.symbol)}`} className="focus-visible:outline focus-visible:outline-2 rounded"
              style={{ color: theme.colors.text, outlineColor: theme.colors.primary }} aria-label={fill(t.stock.openPage, { symbol: h.symbol })}>
              {h.symbol}
            </Link>
            <AssetBadge type={h.asset_type} />
          </p>
          <p className="text-[12px] max-w-[240px] truncate" style={{ color: theme.colors.textSub }} title={h.name ?? undefined}>
            {h.name ?? DASH}{h.account_name ? ` · ${h.account_name}` : ''}
          </p>
        </th>
        <td className={`${td} text-right tabular-nums`}>
          <p className="text-[14px]" style={{ color: theme.colors.text }}>{price != null ? money(price, ccy, locale) : DASH}</p>
          <DayMove h={h} ccy={ccy} withAmount className="text-[12px]" />
        </td>
        <td className={`${td} text-right tabular-nums text-[14px]`} style={{ color: theme.colors.text }}>
          {p?.value != null ? mm(p.value, ccy, locale) : <span style={{ color: theme.colors.textHint }}>{DASH}</span>}
          {p?.value != null && ccy !== 'CAD' && p.value_cad != null && (
            <p className="text-[11.5px]" style={{ color: theme.colors.textHint }}>≈ {mm(p.value_cad, 'CAD', locale, 0)}</p>
          )}
          {h.shares ? <p className="text-[12px]" style={{ color: theme.colors.textSub }}>{fill(h.shares === 1 ? th.list.shareOne : th.list.shares, { n: num(h.shares, locale) })}</p> : null}
        </td>
        <td className={`${td} text-right tabular-nums text-[13px]`} style={{ color: changeColor(p?.unrealized, theme.colors.up, theme.colors.down, theme.colors.textSub) }}>
          {p?.unrealized != null ? <>{mm(p.unrealized, ccy, locale)}<p className="text-[12px]">{spct(p.unrealized_pct, 1)}</p></> : DASH}
        </td>
        <td className={`${td} text-right tabular-nums text-[13px]`} style={{ color: changeColor(st.change_1m_pct, theme.colors.up, theme.colors.down, theme.colors.textSub) }}>{spct(st.change_1m_pct, 1)}</td>
        <td className={`${td} text-right tabular-nums text-[13px]`} style={{ color: changeColor(ytd, theme.colors.up, theme.colors.down, theme.colors.textSub) }}>{spct(ytd, 1)}</td>
        <td className={`${td} text-right tabular-nums text-[13px]`}>
          {p?.weight_pct != null ? (
            <span style={{ color: p.overweight ? theme.colors.down : theme.colors.text }}>{pct(p.weight_pct, 1)}</span>
          ) : <span style={{ color: theme.colors.textHint }}>{DASH}</span>}
        </td>
        <td className={td}><ChipList chips={chips} /></td>
        {showVerdict && <td className={td}><VerdictChip h={h} /></td>}
        <td className={`${td} w-[52px]`}>
          <RowMenu {...props} onEdit={() => setEditing((e) => !e)} onToggleNotes={() => setOpen((o) => !o)} hasNotes={hasNotes} />
        </td>
      </tr>
      {(editing || open) && (
        <tr style={{ backgroundColor: theme.colors.surface }}>
          <td colSpan={cols} className="px-3 pb-3">
            <div className="flex flex-col gap-2">
              {open && <ReviewDetails h={h} />}
              {editing && <HoldingEditor h={h} onClose={() => setEditing(false)} />}
            </div>
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
  const showVerdict = useAccess().can('action.holdings.review')
  const thc = 'px-3 py-2 text-[12px] font-medium whitespace-nowrap'
  return (
    <>
      <ul className="flex flex-col gap-2 lg:hidden">
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
              <th scope="col" className={`${thc} text-right`}>{th.list.value}</th>
              <th scope="col" className={`${thc} text-right`}>{th.list.gain}</th>
              <th scope="col" className={`${thc} text-right`}>{th.list.m1}</th>
              <th scope="col" className={`${thc} text-right`}>{th.list.ytd}</th>
              <th scope="col" className={`${thc} text-right`}>{th.list.weight}</th>
              <th scope="col" className={thc}>{th.list.status}</th>
              {showVerdict && <th scope="col" className={thc}>{th.list.verdict}</th>}
              <th scope="col" className={thc}><span className="sr-only">{th.list.actions}</span></th>
            </tr>
          </thead>
          <tbody>
            {items.map((h) => (
              <HoldingRow key={h.id} h={h} maxWeight={maxWeight} reviewing={reviewingId === h.id}
                reviewBusy={reviewBusy} onReview={onReview} showVerdict={showVerdict} />
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}
