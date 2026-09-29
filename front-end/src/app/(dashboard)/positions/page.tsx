'use client'

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { client } from '@/lib/api'
import { Skeleton } from '@/components/ui/Skeleton'
import { Sidebar } from '@/components/layout/Sidebar'
import { PositionsHero } from '@/components/positions/PositionsHero'
import { OpenPositionsTab } from '@/components/positions/OpenPositionsTab'
import { TradeHistoryTab } from '@/components/positions/TradeHistoryTab'
import { WalletTab } from '@/components/positions/WalletTab'
import type { TrackRecordData, VirtualSummary, WatchdogEvent } from '@/components/positions/types'

const TABS = ['positions', 'history', 'wallet'] as const
type TabId = (typeof TABS)[number]

function isTab(v: string | null): v is TabId {
  return !!v && (TABS as readonly string[]).includes(v)
}

function PositionsLoading() {
  return (
    <div className="space-y-4">
      <Skeleton width={250} height={28} />
      <div className="grid grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} width="100%" height={90} borderRadius={14} />)}
      </div>
      <Skeleton width="100%" height={300} borderRadius={14} />
    </div>
  )
}

function PositionsContent() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const queryClient = useQueryClient()
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const tabParam = searchParams.get('tab')
  const activeTab: TabId = isTab(tabParam) ? tabParam : 'positions'
  const tabRefs = useRef<Record<TabId, HTMLButtonElement | null>>({ positions: null, history: null, wallet: null })

  const [autoRefresh, setAutoRefresh] = useState(false)
  const [refreshInterval] = useState(15)
  const [countdown, setCountdown] = useState(15)

  const { data, isLoading, isFetching } = useQuery<VirtualSummary>({
    queryKey: ['stats', 'virtual-portfolio'],
    queryFn: async () => (await client.get<VirtualSummary>('/stats/virtual-portfolio')).data,
    staleTime: 30_000,
    refetchInterval: autoRefresh ? refreshInterval * 1000 : false,
  })

  const { data: watchdogEvents } = useQuery<WatchdogEvent[]>({
    queryKey: ['stats', 'watchdog-events'],
    queryFn: async () => (await client.get<WatchdogEvent[]>('/stats/watchdog-events?limit=50')).data,
    staleTime: 30_000,
  })

  const { data: signalsData } = useQuery<{ signals: { symbol: string; is_discovered?: boolean }[] }>({
    queryKey: ['signals', 'discovered-check'],
    queryFn: async () => (await client.get('/signals?limit=200')).data,
    staleTime: 60_000,
  })

  const { data: trackRecord } = useQuery<TrackRecordData>({
    queryKey: ['signals', 'track-record'],
    queryFn: async () => (await client.get('/signals/track-record')).data,
    staleTime: 60_000,
  })

  // Auto-refresh countdown
  useEffect(() => {
    if (!autoRefresh) return
    setCountdown(refreshInterval)
    const timer = setInterval(() => {
      setCountdown((c) => {
        if (c <= 1) return refreshInterval
        return c - 1
      })
    }, 1000)
    return () => clearInterval(timer)
  }, [autoRefresh, refreshInterval])

  const handleRefresh = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['stats', 'virtual-portfolio'] })
    queryClient.invalidateQueries({ queryKey: ['stats', 'watchdog-events'] })
    setCountdown(refreshInterval)
  }, [queryClient, refreshInterval])

  const toggleAutoRefresh = useCallback(() => setAutoRefresh((v) => !v), [])

  // Symbols with recent watchdog events — must be before early return (Rules of Hooks)
  const recentEvents = data?.watchdog?.recent_events
  const monitoredSymbols = useMemo(
    () => new Set(recentEvents?.map(e => e.symbol) ?? []),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [recentEvents?.length],
  )

  // Symbols found via discovery (not in core universe)
  const discoveredSymbols = useMemo(
    () => new Set(signalsData?.signals?.filter(s => s.is_discovered).map(s => s.symbol) ?? []),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [signalsData?.signals?.length],
  )

  const selectTab = useCallback((tab: TabId, focus = false) => {
    const params = new URLSearchParams(searchParams.toString())
    if (tab === 'positions') params.delete('tab')
    else params.set('tab', tab)
    const qs = params.toString()
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false })
    if (focus) tabRefs.current[tab]?.focus()
  }, [router, pathname, searchParams])

  const onTabKeyDown = useCallback((e: React.KeyboardEvent<HTMLButtonElement>) => {
    const i = TABS.indexOf(activeTab)
    let next: TabId | null = null
    if (e.key === 'ArrowRight') next = TABS[(i + 1) % TABS.length]
    else if (e.key === 'ArrowLeft') next = TABS[(i - 1 + TABS.length) % TABS.length]
    else if (e.key === 'Home') next = TABS[0]
    else if (e.key === 'End') next = TABS[TABS.length - 1]
    if (next) {
      e.preventDefault()
      selectTab(next, true)
    }
  }, [activeTab, selectTab])

  if (isLoading) return <PositionsLoading />

  const brain = data?.brain ?? { open_count: 0, closed_count: 0, wins: 0, losses: 0, win_rate: 0, avg_return_pct: 0, total_return_pct: 0, best_trade: null, worst_trade: null }
  const brainTrades = (data?.open_trades.filter(t => t.source === 'brain') ?? []).sort((a, b) => b.entry_score - a.entry_score)
  const brainClosed = data?.recent_closed.filter(t => t.source === 'brain') ?? []
  const hasClosedData = brain.closed_count > 0

  // Calculate total unrealized P&L across all open brain trades
  const totalUnrealizedPnl = brainTrades.reduce((sum, t) => sum + (t.unrealized_pnl_pct ?? 0), 0)
  const avgUnrealizedPnl = brainTrades.length > 0 ? totalUnrealizedPnl / brainTrades.length : 0

  const tabLabels: Record<TabId, string> = {
    positions: t.positions.tabs.positions,
    history: t.positions.tabs.history,
    wallet: t.positions.tabs.wallet,
  }

  return (
    <div className="space-y-6">
      <PositionsHero
        data={data}
        brain={brain}
        autoRefresh={autoRefresh}
        countdown={countdown}
        isFetching={isFetching}
        onToggleAutoRefresh={toggleAutoRefresh}
        onRefresh={handleRefresh}
      />

      {/* Content + Sidebar */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_300px] gap-6 items-start">
        <div className="space-y-6 min-w-0">
          <div
            role="tablist"
            aria-label={t.positions.tabsLabel}
            className="flex items-center gap-1 pb-3"
            style={{ borderBottom: `1px solid ${theme.colors.border}` }}
          >
            {TABS.map((tab) => {
              const selected = activeTab === tab
              return (
                <button
                  key={tab}
                  ref={(el) => { tabRefs.current[tab] = el }}
                  type="button"
                  role="tab"
                  id={`positions-tab-${tab}`}
                  aria-selected={selected}
                  aria-controls={`positions-panel-${tab}`}
                  tabIndex={selected ? 0 : -1}
                  onClick={() => selectTab(tab)}
                  onKeyDown={onTabKeyDown}
                  className="text-[12px] px-3 py-1.5 rounded-lg transition-colors outline-none focus-visible:ring-2 focus-visible:ring-offset-1"
                  style={{
                    color: selected ? theme.colors.primary : theme.colors.textSub,
                    backgroundColor: selected ? theme.colors.primary + '15' : 'transparent',
                    fontWeight: selected ? 600 : 500,
                    ['--tw-ring-color' as string]: theme.colors.primary,
                    ['--tw-ring-offset-color' as string]: theme.colors.bg,
                  } as React.CSSProperties}
                >
                  {tabLabels[tab]}
                </button>
              )
            })}
          </div>

          <div
            role="tabpanel"
            id={`positions-panel-${activeTab}`}
            aria-labelledby={`positions-tab-${activeTab}`}
            tabIndex={0}
            className="outline-none"
          >
            {activeTab === 'positions' && (
              <OpenPositionsTab
                data={data}
                brain={brain}
                brainTrades={brainTrades}
                brainClosed={brainClosed}
                hasClosedData={hasClosedData}
                avgUnrealizedPnl={avgUnrealizedPnl}
                watchdogEvents={watchdogEvents}
                monitoredSymbols={monitoredSymbols}
                discoveredSymbols={discoveredSymbols}
              />
            )}
            {activeTab === 'history' && (
              <TradeHistoryTab data={data} brain={brain} brainClosed={brainClosed} trackRecord={trackRecord} />
            )}
            {activeTab === 'wallet' && <WalletTab />}
          </div>
        </div>
        <div className="sticky top-6 hidden lg:block">
          <Sidebar />
        </div>
      </div>
    </div>
  )
}

export default function PositionsPage() {
  return (
    <Suspense fallback={<PositionsLoading />}>
      <PositionsContent />
    </Suspense>
  )
}
