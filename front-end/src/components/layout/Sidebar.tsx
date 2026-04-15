'use client'

import { useMemo } from 'react'
import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useAllSignals } from '@/hooks/useSignals'
import { client } from '@/lib/api'
import { WatchlistTable } from '@/components/watchlist/WatchlistTable'
import { BrainPerformanceWidget } from '@/components/dashboard/DashboardWidgets'
import { Card } from '@/components/ui/Card'
import { Database, Send, Brain, Zap, Sparkles, Clock, Eye } from 'lucide-react'

interface Integration {
  status: string
  ok: boolean
}

const ICONS: Record<string, typeof Brain> = {
  supabase: Database,
  telegram: Send,
  claude: Brain,
  grok: Zap,
  gemini: Sparkles,
  scheduler: Clock,
  watchdog: Eye,
}

function ConnectionStatus() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)

  const { data } = useQuery<{ status: string; integrations: Record<string, Integration> }>({
    queryKey: ['health', 'integrations'],
    queryFn: async () => (await client.get('/health/integrations')).data,
    staleTime: 60_000,
    refetchInterval: 60_000,
  })

  if (!data) return null

  const entries = Object.entries(data.integrations)
  const allOk = entries.every(([, v]) => v.ok)

  return (
    <Link href="/integrations">
      <Card>
        <div className="flex items-center justify-between mb-2">
          <span className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: theme.colors.textSub }}>
            {t.integrations.title}
          </span>
          <span
            className="text-[9px] font-bold px-1.5 py-0.5 rounded"
            style={{
              backgroundColor: (allOk ? theme.colors.up : theme.colors.down) + '18',
              color: allOk ? theme.colors.up : theme.colors.down,
            }}
          >
            {allOk ? t.integrations.allOk : t.integrations.degraded}
          </span>
        </div>
        <div className="space-y-1.5">
          {entries.map(([key, integration]) => {
            const Icon = ICONS[key] || Zap
            return (
              <div key={key} className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Icon size={12} style={{ color: integration.ok ? theme.colors.textSub : theme.colors.down }} />
                  <span className="text-[11px]" style={{ color: theme.colors.text }}>
                    {key}{key === 'claude' && integration.status === 'local' ? ` ${t.signal.local}` : ''}
                  </span>
                </div>
                <div className="flex items-center gap-1">
                  <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: integration.ok ? theme.colors.up : theme.colors.down }} />
                </div>
              </div>
            )
          })}
        </div>
      </Card>
    </Link>
  )
}

export function Sidebar() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const { data: signals } = useAllSignals({ limit: 50 })

  // Fetch brain's open positions to exclude from radar
  const { data: portfolio } = useQuery<{ open_trades: { symbol: string }[] }>({
    queryKey: ['stats', 'virtual-portfolio'],
    queryFn: async () => (await client.get('/stats/virtual-portfolio')).data,
    staleTime: 60_000,
  })
  const heldSymbols = useMemo(
    () => new Set((portfolio?.open_trades ?? []).map((t) => t.symbol)),
    [portfolio],
  )

  // Brain Radar: BUY signals scored 72+ that the brain DOESN'T already hold.
  // If it's already in Open Positions, showing it here is redundant.
  const brainPicks = useMemo(() => {
    if (!signals) return []
    const buys = signals
      .filter((s) => s.action === 'BUY' && s.score >= 72 && !heldSymbols.has(s.symbol))
      .sort((a, b) => b.score - a.score)
    const equity = buys.filter((s) => s.asset_type !== 'CRYPTO').slice(0, 3)
    const crypto = buys.filter((s) => s.asset_type === 'CRYPTO').slice(0, 3)
    return [...equity, ...crypto]
  }, [signals, heldSymbols])

  return (
    <aside className="hidden lg:flex flex-col gap-3 w-[300px] shrink-0">
      <Card>
        <h3 className="text-[11px] font-semibold uppercase tracking-wide mb-2" style={{ color: theme.colors.textSub }}>
          {t.overview.watchlist}
        </h3>
        <WatchlistTable signals={signals} compact />
      </Card>
      {brainPicks.length > 0 && (
        <Card>
          <h3 className="text-[11px] font-semibold uppercase tracking-wide mb-2" style={{ color: theme.colors.textSub }}>
            {t.overview.brainRadar ?? 'Brain Radar'}
          </h3>
          <div className="flex flex-wrap gap-1.5">
            {brainPicks.map((sig) => (
              <Link key={sig.id} href={`/signals/${sig.symbol}`}>
                <div
                  className="flex items-center gap-1.5 px-2 py-1 rounded-md transition-opacity hover:opacity-80"
                  style={{ backgroundColor: theme.colors.surfaceAlt, border: `1px solid ${theme.colors.border}` }}
                >
                  <span className="text-[11px] font-semibold" style={{ color: theme.colors.text }}>
                    {sig.symbol}
                  </span>
                  <span className="text-[10px] font-bold tabular-nums" style={{ color: theme.colors.up }}>
                    {sig.score}
                  </span>
                </div>
              </Link>
            ))}
          </div>
        </Card>
      )}
      <BrainPerformanceWidget />
      <ConnectionStatus />
    </aside>
  )
}
