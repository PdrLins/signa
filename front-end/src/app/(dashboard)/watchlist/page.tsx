'use client'

import { useState, useEffect, useRef } from 'react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useWatchlist, useAddTicker } from '@/hooks/useWatchlist'
import { useToast } from '@/hooks/useToast'
import { client } from '@/lib/api'
import { WatchlistTable } from '@/components/watchlist/WatchlistTable'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Sidebar } from '@/components/layout/Sidebar'
import { Search } from 'lucide-react'

interface SearchResult {
  symbol: string
  name: string
  exchange: string
  price: number
  type: string
}

export default function WatchlistPage() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const toast = useToast()
  const { data: items } = useWatchlist()
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [searching, setSearching] = useState(false)
  const [showDropdown, setShowDropdown] = useState(false)
  const addTicker = useAddTicker()
  const dropdownRef = useRef<HTMLDivElement>(null)
  const timerRef = useRef<NodeJS.Timeout>()

  // Debounced search
  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
    const q = query.trim()
    if (q.length < 1) {
      setResults([])
      setShowDropdown(false)
      return
    }
    timerRef.current = setTimeout(async () => {
      setSearching(true)
      try {
        const res = await client.get<{ results: SearchResult[] }>(`/watchlist/search?q=${encodeURIComponent(q)}`)
        setResults(res.data.results)
        setShowDropdown(res.data.results.length > 0)
      } catch {
        setResults([])
      }
      setSearching(false)
    }, 400)
    return () => { if (timerRef.current) clearTimeout(timerRef.current) }
  }, [query])

  // Close dropdown on click outside
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setShowDropdown(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const handleAdd = (symbol: string) => {
    setShowDropdown(false)
    setQuery('')
    addTicker.mutate(symbol, {
      onSuccess: () => toast.show(`${symbol} ${t.signal.addedToWatchlist}`, 'success'),
      onError: (err) => toast.show(err?.message || t.watchlist.addFailed, 'error'),
    })
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const value = query.trim().toUpperCase()
    if (!value) return
    if (results.length > 0) {
      handleAdd(results[0].symbol)
    } else {
      handleAdd(value)
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold" style={{ color: theme.colors.text }}>{t.watchlist.title}</h1>
        {items && (
          <p className="text-sm mt-1" style={{ color: theme.colors.textSub }}>
            {items.length} {items.length === 1 ? 'ticker' : 'tickers'}
          </p>
        )}
      </div>

      {/* Search + Add */}
      <div className="relative" ref={dropdownRef}>
        <form onSubmit={handleSubmit} className="flex gap-2">
          <div className="relative flex-1">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: theme.colors.textHint }} />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t.watchlist.placeholder}
              className="w-full rounded-[11px] pl-10 pr-4 py-3 text-sm outline-none"
              style={{
                backgroundColor: theme.colors.surfaceAlt,
                color: theme.colors.text,
                border: `0.5px solid ${theme.colors.border}`,
              }}
            />
            {searching && (
              <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px]" style={{ color: theme.colors.textHint }}>
                ...
              </span>
            )}
          </div>
          <Button type="submit" disabled={!query.trim() || addTicker.isPending}>
            {addTicker.isPending ? t.watchlist.adding : t.watchlist.add}
          </Button>
        </form>

        {/* Search results dropdown */}
        {showDropdown && results.length > 0 && (
          <div
            className="absolute left-0 right-0 mt-1 rounded-xl overflow-hidden z-50"
            style={{
              backgroundColor: theme.colors.surface,
              border: `1px solid ${theme.colors.border}`,
              boxShadow: theme.isDark ? '0 8px 24px rgba(0,0,0,0.4)' : '0 8px 24px rgba(0,0,0,0.1)',
            }}
          >
            {results.map((r) => (
              <button
                key={r.symbol}
                onClick={() => handleAdd(r.symbol)}
                className="w-full flex items-center justify-between px-4 py-3 transition-colors text-left"
                style={{ borderBottom: `1px solid ${theme.colors.border}20` }}
                onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = theme.colors.surfaceAlt)}
                onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
              >
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-bold" style={{ color: theme.colors.text }}>{r.symbol}</span>
                    <span
                      className="text-[9px] font-semibold px-1.5 py-0.5 rounded"
                      style={{ backgroundColor: r.type === 'CRYPTO' ? theme.colors.warning + '15' : theme.colors.primary + '15', color: r.type === 'CRYPTO' ? theme.colors.warning : theme.colors.primary }}
                    >
                      {r.type}
                    </span>
                  </div>
                  <span className="text-[11px]" style={{ color: theme.colors.textSub }}>{r.name}</span>
                </div>
                <span className="text-sm font-semibold tabular-nums" style={{ color: theme.colors.text }}>
                  ${r.price?.toFixed(2)}
                </span>
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_300px] gap-6 items-start">
        <div className="space-y-5">
          <Card padding="16px">
            <WatchlistTable />
          </Card>
        </div>
        <div className="sticky top-6 hidden lg:block">
          <Sidebar />
        </div>
      </div>
    </div>
  )
}
