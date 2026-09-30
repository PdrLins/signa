'use client'

import { memo, useMemo } from 'react'
import Link from 'next/link'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { fill } from '@/lib/insights'
import { pct, spct } from '@/components/holdings/format'
import type { AllocationTile } from '@/types/tracker'

interface Rect { x: number; y: number; w: number; h: number }
interface Placed extends Rect { tile: AllocationTile }

/** Binary-split treemap: halve the (descending) list by weight, split the
 *  rectangle along its longer side in the same proportion, recurse. Pure. */
export function layoutTreemap(tiles: AllocationTile[], rect: Rect): Placed[] {
  const items = tiles.filter((t) => t.weight_pct > 0)
  const out: Placed[] = []
  const walk = (list: AllocationTile[], r: Rect) => {
    if (list.length === 0) return
    if (list.length === 1) { out.push({ ...r, tile: list[0] }); return }
    const total = list.reduce((s, t) => s + t.weight_pct, 0)
    let acc = 0
    let cut = 0
    // first group: grow until it holds about half the weight (at least one item)
    for (let i = 0; i < list.length - 1; i++) {
      acc += list[i].weight_pct
      cut = i + 1
      if (acc >= total / 2) break
    }
    const share = total > 0 ? acc / total : 0.5
    const a = list.slice(0, cut)
    const b = list.slice(cut)
    if (r.w >= r.h) {
      walk(a, { x: r.x, y: r.y, w: r.w * share, h: r.h })
      walk(b, { x: r.x + r.w * share, y: r.y, w: r.w * (1 - share), h: r.h })
    } else {
      walk(a, { x: r.x, y: r.y, w: r.w, h: r.h * share })
      walk(b, { x: r.x, y: r.y + r.h * share, w: r.w, h: r.h * (1 - share) })
    }
  }
  walk(items.slice().sort((p, q) => q.weight_pct - p.weight_pct), rect)
  return out
}

// Layout space: 100 wide × 62 tall (the container keeps the same aspect).
const W = 100
const H = 62

function alpha(v: number | null, scale: number): string {
  if (v === null || !Number.isFinite(v)) return '22'
  const a = Math.min(1, Math.abs(v) / scale)
  return Math.round(60 + a * 150).toString(16).padStart(2, '0')
}

const Tile = memo(function Tile({ p, by }: { p: Placed; by: 'day' | 'total' }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const v = by === 'day' ? p.tile.day_change_pct : p.tile.total_gain_pct
  const base = v === null ? theme.colors.textSub : v >= 0 ? theme.colors.up : theme.colors.down
  const big = p.w > 13 && p.h > 11
  const label = fill(t.insightsPage.allocation.tileAria, { symbol: p.tile.symbol, weight: pct(p.tile.weight_pct, 1), change: spct(v, 1) })
  return (
    <Link href={`/stocks/${encodeURIComponent(p.tile.symbol)}`} aria-label={label} title={label}
      className="absolute overflow-hidden flex flex-col items-center justify-center text-center leading-tight focus-visible:outline focus-visible:outline-2 focus-visible:z-10"
      style={{
        left: `${(p.x / W) * 100}%`, top: `${(p.y / H) * 100}%`, width: `${(p.w / W) * 100}%`, height: `${(p.h / H) * 100}%`,
        backgroundColor: base + alpha(v, by === 'day' ? 3 : 30),
        border: `1px solid ${theme.colors.surface}`, color: theme.colors.text, outlineColor: theme.colors.primary,
      }}>
      {big && (
        <>
          <span className="text-[12px] font-bold truncate max-w-full px-0.5">{p.tile.symbol.replace(/\.TO$/, '')}</span>
          <span className="text-[10.5px] tabular-nums">{spct(v, 1)}</span>
        </>
      )}
    </Link>
  )
})

/** Holdings map: tiles sized by weight, coloured by today's or total gain. */
export const Treemap = memo(function Treemap({ tiles, by }: { tiles: AllocationTile[]; by: 'day' | 'total' }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const placed = useMemo(() => layoutTreemap(tiles, { x: 0, y: 0, w: W, h: H }), [tiles])
  return (
    <div role="group" aria-label={t.insightsPage.allocation.mapAria} className="relative w-full rounded-xl overflow-hidden"
      style={{ aspectRatio: `${W} / ${H}`, backgroundColor: theme.colors.surfaceAlt }}>
      {placed.map((p) => <Tile key={p.tile.symbol} p={p} by={by} />)}
    </div>
  )
})
