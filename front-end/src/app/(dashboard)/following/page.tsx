'use client'

import { memo, useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { Briefcase, Plus, Star } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useAccess } from '@/hooks/useAccess'
import { useCardLink } from '@/hooks/useCardLink'
import { useFollow } from '@/hooks/useFollow'
import { useFollowing } from '@/hooks/useWatchlist'
import { useOverlayStore } from '@/store/overlayStore'
import { DASH, fill, nativePrice, signedPct } from '@/lib/insights'
import { SearchButton } from '@/components/search/GlobalSearch'
import { SlotMeter } from '@/components/upgrade/SlotMeter'
import { SparkLine } from '@/components/ui/SparkLine'
import { Freshness, QueryError, SkeletonCards } from '@/components/tracker/ui'
import type { FollowingRow, SuggestionItem } from '@/types/watchlist'
import { SegmentedTabs } from '@/components/ui/SegmentedTabs'

/** Following: every stock the user follows, priced, one tap from its page.
 *  Followed symbols are what the free plan limits (10), so following is
 *  made easy here: "+ Follow" opens the global search, suggestions follow
 *  in one tap, and the slot meter is always in view on Free. */
export default function FollowingPage() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const tf = t.following
  const { can, slots } = useAccess()
  const canEdit = can('action.watchlist.edit')
  const q = useFollowing()
  const openSearch = useOverlayStore((s) => s.openSearch)
  const openUpgrade = useOverlayStore((s) => s.openUpgrade)
  const full = !!slots && slots.limit !== null && slots.used >= slots.limit
  const onFollow = () => (full ? openUpgrade('slot_limit', slots?.limit ?? null) : openSearch())

  const data = q.data
  const watched = useMemo(() => data?.watched ?? [], [data])
  const held = useMemo(() => data?.held ?? [], [data])
  const nothing = !!data && watched.length === 0 && held.length === 0

  return (
    <div className="space-y-5 pb-4 min-w-0 max-w-4xl">
      <header className="flex items-start justify-between gap-3 min-w-0">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold" style={{ color: theme.colors.text }}>{tf.title}</h1>
          <p className="text-[13px] mt-0.5" style={{ color: theme.colors.textSub }}>{tf.subtitle}</p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <SearchButton />
          {canEdit && (
            <button type="button" onClick={onFollow}
              className="min-h-[44px] px-4 rounded-xl text-[14px] font-semibold inline-flex items-center gap-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
              style={{ backgroundColor: theme.colors.primary, color: theme.colors.surface, outlineColor: theme.colors.primary }}>
              <Plus size={16} aria-hidden="true" />{tf.follow}
            </button>
          )}
        </div>
      </header>

      {slots && slots.limit !== null && (
        <div className="flex flex-wrap items-end gap-x-4 gap-y-1">
          <SlotMeter />
          <Link href="/pricing" className="text-[13px] font-medium min-h-[44px] inline-flex items-center rounded focus-visible:outline focus-visible:outline-2"
            style={{ color: theme.colors.primary, outlineColor: theme.colors.primary }}>
            {tf.unlimited}
          </Link>
        </div>
      )}

      {q.isLoading && <SkeletonCards heights={[64, 64, 64, 64]} />}
      {q.error && !data && <QueryError error={q.error} onRetry={() => q.refetch()} />}

      {nothing && (
        <section className="rounded-2xl p-5 flex flex-col items-start gap-3" aria-labelledby="following-empty"
          style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.border}` }}>
          <h2 id="following-empty" className="text-[17px] font-semibold" style={{ color: theme.colors.text }}>{tf.emptyTitle}</h2>
          <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{tf.emptyBody}</p>
        </section>
      )}

      {watched.length > 0 && (
        <RowSection id="following-watched" title={fill(tf.watching, { n: watched.length })} rows={watched} canEdit={canEdit} />
      )}
      {held.length > 0 && (
        <RowSection id="following-held" title={fill(tf.youOwn, { n: held.length })} hint={tf.youOwnHint} rows={held} canEdit={false} />
      )}

      {data && canEdit && data.suggestions.length > 0 && <Suggestions groups={data.suggestions} />}

      {data && <Freshness asOf={data.as_of} delayed={data.delayed_minutes} />}
    </div>
  )
}

function RowSection({ id, title, hint, rows, canEdit }: {
  id: string; title: string; hint?: string; rows: FollowingRow[]; canEdit: boolean
}) {
  const theme = useTheme()
  return (
    <section aria-labelledby={id} className="flex flex-col gap-2 min-w-0">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
        <h2 id={id} className="text-[15px] font-semibold" style={{ color: theme.colors.text }}>{title}</h2>
        {hint && <p className="text-[12px]" style={{ color: theme.colors.textHint }}>{hint}</p>}
      </div>
      <ul className="rounded-2xl overflow-hidden" style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.border}` }}>
        {rows.map((r, i) => <Row key={r.symbol} row={r} first={i === 0} canEdit={canEdit} />)}
      </ul>
    </section>
  )
}

const Row = memo(function Row({ row, first, canEdit }: { row: FollowingRow; first: boolean; canEdit: boolean }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const tf = t.following
  const href = `/stocks/${encodeURIComponent(row.symbol)}`
  const link = useCardLink(href)
  const { unfollow, busy } = useFollow()
  const chg = row.change_pct
  const color = chg == null || chg === 0 ? theme.colors.textSub : chg > 0 ? theme.colors.up : theme.colors.down
  const trendUp = row.spark.length >= 2 ? row.spark[row.spark.length - 1] >= row.spark[0] : true
  return (
    <li onClick={link.onClick} className={`flex items-center gap-3 pl-4 pr-1 py-2.5 min-w-0 hover:brightness-110 ${link.className}`}
      style={{ borderTop: first ? undefined : `1px solid ${theme.colors.border}`, backgroundColor: theme.colors.surface }}>
      <div className="min-w-0 flex-1">
        <Link href={href} className="font-mono font-semibold text-[15px] rounded focus-visible:outline focus-visible:outline-2"
          style={{ color: theme.colors.text, outlineColor: theme.colors.primary }} aria-label={fill(t.stock.openPage, { symbol: row.symbol })}>
          {row.symbol}
        </Link>
        <p className="text-[12px] truncate flex items-center gap-1.5" style={{ color: theme.colors.textSub }}>
          {row.in_holdings && <Briefcase size={11} aria-label={tf.owned} style={{ color: theme.colors.primary }} />}
          <span className="truncate">{row.name ?? DASH}</span>
        </p>
      </div>
      <span className="hidden sm:block shrink-0" aria-hidden="true">
        <SparkLine data={row.spark} positive={trendUp} width={88} height={30} />
      </span>
      <div className="text-right shrink-0 tabular-nums min-w-[92px]">
        <p className="text-[15px] font-semibold" style={{ color: theme.colors.text }}>
          {row.price != null ? nativePrice(row.price, row.symbol, row.currency ?? undefined) : DASH}
        </p>
        <p className="text-[12.5px] font-medium" style={{ color }}>{chg == null ? DASH : signedPct(chg, 2)}</p>
        {row.extended && (
          <p className="text-[11px] font-medium" title={tf.extendedTitle}
            style={{ color: (row.extended.change_pct ?? 0) >= 0 ? theme.colors.up : theme.colors.down }}>
            {row.extended.session === 'pre' ? tf.preShort : tf.postShort} {signedPct(row.extended.change_pct, 2)}
          </p>
        )}
      </div>
      {canEdit ? (
        <button type="button" onClick={() => unfollow(row.symbol)} disabled={busy}
          aria-label={fill(tf.unfollowAria, { symbol: row.symbol })} title={tf.unfollow}
          className="shrink-0 min-h-[44px] min-w-[44px] rounded-full inline-flex items-center justify-center disabled:opacity-50 focus-visible:outline focus-visible:outline-2"
          style={{ color: theme.colors.warning, outlineColor: theme.colors.primary }}>
          <Star size={18} fill={theme.colors.warning} aria-hidden="true" />
        </button>
      ) : <span className="w-[44px] shrink-0" aria-hidden="true" />}
    </li>
  )
})

/** Ideas to follow: one group at a time (segmented control in the server's
 *  group order) with a one-line "why", shown as normal rows. A row followed
 *  here stays in place with a gold star until the page is opened again (the
 *  server leaves followed symbols out of the next answer). */
function Suggestions({ groups }: { groups: { key: string; items: SuggestionItem[] }[] }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const tf = t.following
  const { follow, busy, pendingSymbol } = useFollow()
  // first answer per group, so a followed row doesn't jump away on refetch
  const [snap, setSnap] = useState<Record<string, SuggestionItem[]>>({})
  const [followed, setFollowed] = useState<Set<string>>(new Set())
  const [active, setActive] = useState<string>(groups[0]?.key ?? '')
  useEffect(() => {
    setSnap((prev) => {
      let changed = false
      const next = { ...prev }
      for (const g of groups) {
        if (!next[g.key]) { next[g.key] = g.items; changed = true }
        else {   // refresh prices of rows still listed, keep the followed ones
          const fresh = new Map(g.items.map((i) => [i.symbol, i]))
          const merged = next[g.key].map((i) => fresh.get(i.symbol) ?? i)
          if (merged.some((m, i) => m !== next[g.key][i])) { next[g.key] = merged; changed = true }
        }
      }
      return changed ? next : prev
    })
  }, [groups])
  useEffect(() => { if (!groups.some((g) => g.key === active) && groups[0]) setActive(groups[0].key) }, [groups, active])

  const options = useMemo(() => groups.map((g) => ({
    value: g.key, label: (tf.groupsShort as Record<string, string>)[g.key] ?? g.key,
  })), [groups, tf])
  const items = snap[active] ?? []
  const onFollow = (symbol: string) => {
    follow(symbol)
    setFollowed((s) => new Set(s).add(symbol))
  }

  return (
    <section aria-labelledby="following-ideas" className="flex flex-col gap-3 min-w-0">
      <div>
        <h2 id="following-ideas" className="text-[15px] font-semibold" style={{ color: theme.colors.text }}>{tf.ideasTitle}</h2>
        <p className="text-[12px]" style={{ color: theme.colors.textHint }}>{tf.ideasHint}</p>
      </div>
      <SegmentedTabs value={active} options={options} onChange={setActive} label={tf.ideasTitle} idBase="ideas-tab" />
      <p className="text-[13px] -mt-1" style={{ color: theme.colors.textSub }}>{(tf.groupsWhy as Record<string, string>)[active] ?? ''}</p>
      <ul id="ideas-tab-panel" role="tabpanel" aria-labelledby={`ideas-tab-${active}`}
        className="rounded-2xl overflow-hidden" style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.border}` }}>
        {items.map((it, i) => {
          const on = followed.has(it.symbol)
          const chg = it.change_pct ?? null
          const color = chg == null || chg === 0 ? theme.colors.textSub : chg > 0 ? theme.colors.up : theme.colors.down
          return (
            <li key={it.symbol} className="flex items-center gap-3 pl-4 pr-1 py-2 min-w-0"
              style={{ borderTop: i ? `1px solid ${theme.colors.border}` : undefined }}>
              <Link href={`/stocks/${encodeURIComponent(it.symbol)}`} className="min-w-0 flex-1 rounded focus-visible:outline focus-visible:outline-2"
                style={{ outlineColor: theme.colors.primary }}>
                <span className="block font-mono font-semibold text-[14px]" style={{ color: theme.colors.text }}>{it.symbol}</span>
                <span className="block text-[12px] truncate" style={{ color: theme.colors.textSub }}>{it.name}</span>
              </Link>
              {it.price != null && (
                <div className="text-right shrink-0 tabular-nums">
                  <p className="text-[14px] font-semibold" style={{ color: theme.colors.text }}>{nativePrice(it.price, it.symbol, it.currency ?? undefined)}</p>
                  {chg != null && <p className="text-[12px] font-medium" style={{ color }}>{signedPct(chg, 2)}</p>}
                </div>
              )}
              <button type="button" onClick={() => !on && onFollow(it.symbol)} disabled={on || (busy && pendingSymbol === it.symbol)}
                aria-pressed={on} aria-label={on ? fill(tf.followedAria, { symbol: it.symbol }) : fill(tf.followAria, { symbol: it.symbol, name: it.name })}
                title={on ? tf.followedTitle : tf.follow}
                className="shrink-0 min-h-[44px] min-w-[44px] rounded-full inline-flex items-center justify-center focus-visible:outline focus-visible:outline-2"
                style={{ color: on ? theme.colors.warning : theme.colors.textSub, outlineColor: theme.colors.primary }}>
                <Star size={18} aria-hidden="true" fill={on ? theme.colors.warning : 'none'} />
              </button>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
