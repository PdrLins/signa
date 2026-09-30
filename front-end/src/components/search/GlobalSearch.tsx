'use client'

import { memo, useCallback, useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { Briefcase, Loader2, Plus, Search, Star, X } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useOverlayStore } from '@/store/overlayStore'
import { useAccess } from '@/hooks/useAccess'
import { useSymbolSearch } from '@/hooks/useSymbolSearch'
import { useWatchlist } from '@/hooks/useWatchlist'
import { useHoldings } from '@/hooks/useHoldings'
import { useFollow } from '@/hooks/useFollow'
import { fill } from '@/lib/insights'
import { resolveRawEntry } from '@/components/check/SymbolCombobox'
import type { SymbolMatch } from '@/types/symbols'

/** Header button that opens the global search (every tracker page). */
export function SearchButton() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const { can } = useAccess()
  const open = useOverlayStore((s) => s.openSearch)
  const [mac, setMac] = useState(false)
  useEffect(() => { setMac(/Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent)) }, [])
  if (!can('area.stock')) return null
  const shortcut = mac ? t.search.shortcutMac : t.search.shortcut
  return (
    <button type="button" onClick={open} aria-label={t.search.open} aria-keyshortcuts="Meta+K Control+K"
      title={`${t.search.open} (${shortcut})`}
      className="min-h-[44px] min-w-[44px] rounded-full inline-flex items-center justify-center gap-2 md:px-3 focus-visible:outline focus-visible:outline-2"
      style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.text, outlineColor: theme.colors.primary }}>
      <Search size={18} aria-hidden="true" />
      <kbd className="hidden md:inline text-[11px] font-sans px-1.5 py-px rounded" aria-hidden="true"
        style={{ color: theme.colors.textSub, border: `1px solid ${theme.colors.border}` }}>{shortcut}</kbd>
    </button>
  )
}

const ResultRow = memo(function ResultRow({ m, inHoldings, following, canFollow, canAdd, busy, onOpen, onFollow, onUnfollow, onAdd }: {
  m: SymbolMatch
  inHoldings: boolean
  following: boolean
  canFollow: boolean
  canAdd: boolean
  busy: boolean
  onOpen: (symbol: string) => void
  onFollow: (symbol: string) => void
  onUnfollow: (symbol: string) => void
  onAdd: (symbol: string) => void
}) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const ts = t.search
  const typeLabel = (t.check.search.types as Record<string, string>)[m.type] ?? m.type
  const act = 'min-h-[44px] min-w-[44px] px-2.5 rounded-lg text-[12.5px] font-medium inline-flex items-center justify-center gap-1.5 focus-visible:outline focus-visible:outline-2 disabled:opacity-50'
  return (
    <li className="flex items-center gap-1 min-w-0 px-2 py-1 rounded-xl" style={{ borderTop: `1px solid ${theme.colors.border}` }}>
      <Link href={`/stocks/${encodeURIComponent(m.symbol)}`} data-search-row="1"
        onClick={(e) => { e.preventDefault(); onOpen(m.symbol) }}
        aria-label={fill(ts.openAria, { symbol: m.symbol, name: m.name ?? m.exchange_label })}
        className="flex-1 min-w-0 min-h-[48px] flex flex-col justify-center px-2 rounded-lg focus-visible:outline focus-visible:outline-2"
        style={{ outlineColor: theme.colors.primary }}>
        <span className="flex items-center gap-1.5 flex-wrap min-w-0">
          <span className="text-[14.5px] font-semibold font-mono" style={{ color: theme.colors.text }}>{m.symbol}</span>
          <span className="text-[11.5px]" style={{ color: theme.colors.textSub }}>{m.exchange_label} · {typeLabel}</span>
          {inHoldings && (
            <span className="inline-flex items-center gap-1 text-[10.5px] font-semibold px-1.5 py-px rounded-full"
              style={{ color: theme.colors.primary, border: `1px solid ${theme.colors.primary}` }}>
              <Briefcase size={10} aria-hidden="true" />{ts.inHoldings}
            </span>
          )}
          {following && !inHoldings && (
            <span className="inline-flex items-center gap-1 text-[10.5px] font-semibold px-1.5 py-px rounded-full"
              style={{ color: theme.colors.warning, border: `1px solid ${theme.colors.warning}` }}>
              <Star size={10} aria-hidden="true" />{ts.following}
            </span>
          )}
        </span>
        {m.name && <span className="text-[12.5px] truncate" style={{ color: theme.colors.textSub }}>{m.name}</span>}
      </Link>
      {canFollow && (
        <button type="button" disabled={busy} aria-pressed={following}
          onClick={() => (following ? onUnfollow(m.symbol) : onFollow(m.symbol))}
          aria-label={fill(following ? ts.unfollowAria : ts.followAria, { symbol: m.symbol })}
          className={act} style={{ backgroundColor: theme.colors.surfaceAlt, color: following ? theme.colors.warning : theme.colors.text, outlineColor: theme.colors.primary }}>
          <Star size={15} aria-hidden="true" fill={following ? theme.colors.warning : 'none'} />
          <span className="hidden sm:inline">{following ? ts.following : ts.follow}</span>
        </button>
      )}
      {canAdd && (
        <button type="button" onClick={() => onAdd(m.symbol)} aria-label={fill(ts.addAria, { symbol: m.symbol })}
          className={act} style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.text, outlineColor: theme.colors.primary }}>
          <Plus size={15} aria-hidden="true" />
          <span className="hidden sm:inline">{ts.add}</span>
        </button>
      )}
    </li>
  )
})

function SearchPanel() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const ts = t.search
  const router = useRouter()
  const close = useOverlayStore((s) => s.closeSearch)
  const { can } = useAccess()
  const canFollow = can('action.watchlist.edit')
  const canAdd = can('action.holdings.edit')
  const [q, setQ] = useState('')
  const inputId = useId()
  const titleId = useId()
  const listRef = useRef<HTMLUListElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const { results, settled, loading, isError } = useSymbolSearch(q, { limit: 10 })
  const { follow, unfollow, busy } = useFollow()
  const watch = useWatchlist()
  const holdings = useHoldings()
  const watched = useMemo(() => new Set((watch.data ?? []).map((w) => w.symbol.toUpperCase())), [watch.data])
  const held = useMemo(() => new Set((holdings.data?.items ?? []).map((h) => h.symbol.toUpperCase())), [holdings.data])

  const go = useCallback((href: string) => { close(); router.push(href) }, [close, router])
  const onOpen = useCallback((s: string) => go(`/stocks/${encodeURIComponent(s)}`), [go])
  const onAdd = useCallback((s: string) => go(`/stocks/${encodeURIComponent(s)}?add=1`), [go])

  const rows = () => Array.from(listRef.current?.querySelectorAll<HTMLElement>('[data-search-row]') ?? [])
  const onInputKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); rows()[0]?.focus() }
  }
  const onListKey = (e: KeyboardEvent<HTMLUListElement>) => {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return
    const els = rows()
    const i = els.indexOf(document.activeElement as HTMLElement)
    if (i < 0) return
    e.preventDefault()
    if (e.key === 'ArrowUp' && i === 0) document.getElementById(inputId)?.focus()
    else els[Math.max(0, Math.min(els.length - 1, i + (e.key === 'ArrowDown' ? 1 : -1)))]?.focus()
  }

  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null
    document.getElementById(inputId)?.focus()
    const onKey = (e: globalThis.KeyboardEvent) => {
      // the upgrade sheet (above this panel) handles its own Escape first
      if (e.key === 'Escape' && !useOverlayStore.getState().upgrade) { e.preventDefault(); close() }
    }
    document.addEventListener('keydown', onKey)
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = overflow
      prev?.focus?.()
    }
  }, [inputId, close])

  const typed = q.trim()
  return (
    <div className="fixed inset-0 z-[70] flex items-start justify-center md:pt-[10vh]" role="presentation">
      <div className="absolute inset-0" aria-hidden="true" onClick={close}
        style={{ backgroundColor: `${theme.colors.bg}D9` }} />
      <div ref={panelRef} role="dialog" aria-modal="true" aria-labelledby={titleId}
        className="relative w-full md:max-w-[620px] h-full md:h-auto md:max-h-[75vh] md:rounded-2xl flex flex-col min-w-0"
        style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.border}` }}>
        <h2 id={titleId} className="sr-only">{ts.title}</h2>
        <form role="search" className="flex items-center gap-2 p-3" onSubmit={(e) => {
          e.preventDefault()
          const s = resolveRawEntry(q, results)
          if (s) onOpen(results.find((r) => r.symbol === s)?.symbol ?? s)
        }}>
          <div className="flex-1 flex items-center gap-2 rounded-xl px-3 min-w-0"
            style={{ backgroundColor: theme.colors.surfaceAlt, border: `1px solid ${theme.colors.border}` }}>
            <Search size={16} aria-hidden="true" style={{ color: theme.colors.textHint }} />
            <label htmlFor={inputId} className="sr-only">{ts.title}</label>
            <input id={inputId} type="search" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={onInputKey}
              placeholder={ts.placeholder} autoComplete="off" autoCapitalize="none" autoCorrect="off" spellCheck={false}
              enterKeyHint="search" maxLength={40}
              className="bg-transparent outline-0 min-w-0 flex-1 h-11 text-[16px] md:text-[15px]" style={{ color: theme.colors.text }} />
            {loading && <Loader2 size={15} aria-hidden="true" className="animate-spin" style={{ color: theme.colors.textHint }} />}
          </div>
          <button type="button" onClick={close} aria-label={ts.close}
            className="min-h-[44px] min-w-[44px] rounded-full inline-flex items-center justify-center shrink-0 focus-visible:outline focus-visible:outline-2"
            style={{ color: theme.colors.textSub, outlineColor: theme.colors.primary }}>
            <X size={18} aria-hidden="true" />
          </button>
        </form>
        <div className="flex-1 overflow-y-auto overscroll-contain px-2 pb-3 min-w-0">
          <p className="sr-only" aria-live="polite">
            {settled ? (results.length ? fill(t.check.search.count, { n: results.length }) : fill(ts.noResults, { q: typed })) : ''}
          </p>
          {!typed && <p className="px-3 py-2 text-[13px]" style={{ color: theme.colors.textSub }}>{ts.hint}</p>}
          {typed && isError && <p role="alert" className="px-3 py-2 text-[13px]" style={{ color: theme.colors.down }}>{ts.error}</p>}
          {typed && settled && !results.length && !isError && (
            <p className="px-3 py-2 text-[13px]" style={{ color: theme.colors.textSub }}>{fill(ts.noResults, { q: typed })}</p>
          )}
          {typed && loading && !results.length && (
            <p className="px-3 py-2 text-[13px]" style={{ color: theme.colors.textSub }}>{ts.searching}</p>
          )}
          {results.length > 0 && (
            <ul ref={listRef} aria-label={ts.results} onKeyDown={onListKey} className="flex flex-col">
              {results.map((m) => (
                <ResultRow key={m.symbol} m={m} inHoldings={held.has(m.symbol.toUpperCase())}
                  following={watched.has(m.symbol.toUpperCase())} canFollow={canFollow} canAdd={canAdd} busy={busy}
                  onOpen={onOpen} onFollow={follow} onUnfollow={unfollow} onAdd={onAdd} />
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}

/** Global stock search overlay: ⌘K / Ctrl+K anywhere in the app (or a
 *  header SearchButton). Mounted once in the dashboard layout. */
export function GlobalSearch() {
  const open = useOverlayStore((s) => s.searchOpen)
  const openSearch = useOverlayStore((s) => s.openSearch)
  const closeSearch = useOverlayStore((s) => s.closeSearch)
  const { can } = useAccess()
  const allowed = can('area.stock')
  const pathname = usePathname()

  useEffect(() => { closeSearch() }, [pathname, closeSearch])
  useEffect(() => {
    if (!allowed) return
    const onKey = (e: globalThis.KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && !e.altKey && e.key.toLowerCase() === 'k' && !useOverlayStore.getState().upgrade) {
        e.preventDefault()
        if (useOverlayStore.getState().searchOpen) closeSearch()
        else openSearch()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [allowed, openSearch, closeSearch])

  if (!open || !allowed) return null
  return <SearchPanel />
}
