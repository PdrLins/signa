'use client'

import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTheme } from '@/hooks/useTheme'
import { useToast } from '@/hooks/useToast'
import { useI18nStore } from '@/store/i18nStore'
import { client } from '@/lib/api'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Skeleton } from '@/components/ui/Skeleton'
import { Badge } from '@/components/ui/Badge'
import { Database, Send, Brain, Zap, Sparkles, Clock, RefreshCw, DollarSign, Eye } from 'lucide-react'

interface Integration {
  status: string
  ok: boolean
  detail?: string
  model?: string
}

interface IntegrationsData {
  status: string
  integrations: Record<string, Integration>
}

interface ProviderBudget {
  daily_spend_usd: number
  monthly_spend_usd: number
  monthly_limit_usd: number
  daily_calls: number
  budget_remaining_usd: number
  budget_pct_used: number
  is_free_tier: boolean
}

interface BudgetData {
  daily_limit_usd: number
  monthly_limit_usd: number
  total_monthly_spend_usd: number
  providers: Record<string, ProviderBudget>
}

const META_STATIC: Record<string, { icon: typeof Brain; color: string }> = {
  supabase: { icon: Database, color: '#3ECF8E' },
  telegram: { icon: Send, color: '#29B6F6' },
  claude: { icon: Brain, color: '#D97706' },
  gemini: { icon: Sparkles, color: '#4285F4' },
  grok: { icon: Zap, color: '#1DA1F2' },
  scheduler: { icon: Clock, color: '#8B5CF6' },
  watchdog: { icon: Eye, color: '#F59E0B' },
}

function useMeta() {
  const it = useI18nStore((s) => s.t).integrations
  const names: Record<string, string> = {
    supabase: it.supabase, telegram: it.telegram, claude: it.claude,
    gemini: it.gemini, grok: it.grok, scheduler: it.scheduler, watchdog: it.watchdog,
  }
  const descriptions: Record<string, string> = {
    supabase: it.supabaseDesc, telegram: it.telegramDesc, claude: it.claudeDesc,
    gemini: it.geminiDesc, grok: it.grokDesc, scheduler: it.schedulerDesc, watchdog: it.watchdogDesc,
  }
  return (key: string) => ({
    name: names[key] || key,
    icon: META_STATIC[key]?.icon || Brain,
    color: META_STATIC[key]?.color || '#999',
    description: descriptions[key] || '',
  })
}

function StatusBadge({ status, ok }: { status: string; ok: boolean }) {
  const variant = ok ? 'confirmed'
    : status === 'rate limited' ? 'hold'
    : status === 'no credits' ? 'weakening'
    : 'cancelled'
  return <Badge variant={variant}>{status.toUpperCase()}</Badge>
}

function BudgetBar({ pct, color }: { pct: number; color: string }) {
  const theme = useTheme()
  const barColor = pct > 90 ? theme.colors.down : pct > 70 ? '#F59E0B' : color
  return (
    <div className="w-full h-1.5 rounded-full overflow-hidden" style={{ backgroundColor: theme.colors.surfaceAlt }}>
      <div
        className="h-full rounded-full transition-all duration-500"
        style={{ width: `${Math.min(pct, 100)}%`, backgroundColor: barColor }}
      />
    </div>
  )
}

function BudgetCard({ budget }: { budget: BudgetData }) {
  const theme = useTheme()
  const toast = useToast()
  const queryClient = useQueryClient()
  const it = useI18nStore((s) => s.t).integrations
  const getMeta = useMeta()
  const providers = ['claude', 'grok', 'gemini'] as const
  const [editing, setEditing] = useState(false)
  const [limits, setLimits] = useState({
    daily_limit: budget.daily_limit_usd,
    claude_monthly: budget.providers.claude?.monthly_limit_usd || 5,
    grok_monthly: budget.providers.grok?.monthly_limit_usd || 5,
  })
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    setSaving(true)
    try {
      await client.put('/health/budget', limits)
      toast.show(it.budgetUpdated, 'success')
      queryClient.invalidateQueries({ queryKey: ['health', 'budget'] })
      setEditing(false)
    } catch {
      toast.show(it.failedToUpdateBudget, 'error')
    }
    setSaving(false)
  }

  return (
    <Card>
      <div className="flex items-start gap-4">
        <div
          className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0"
          style={{ backgroundColor: '#10B981' + '15' }}
        >
          <DollarSign size={20} style={{ color: '#10B981' }} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-bold" style={{ color: theme.colors.text }}>{it.budget}</h3>
            <span className="text-[11px] font-mono" style={{ color: theme.colors.textSub }}>
              ${budget.total_monthly_spend_usd.toFixed(2)} {it.spent}
            </span>
          </div>

          <div className="space-y-3">
            {providers.map((p) => {
              const pb = budget.providers[p]
              if (!pb) return null
              const meta = getMeta(p)
              const Icon = meta.icon

              return (
                <div key={p} className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Icon size={14} style={{ color: meta.color }} />
                      <span className="text-xs font-semibold" style={{ color: theme.colors.text }}>
                        {meta.name}
                      </span>
                      {pb.is_free_tier && (
                        <span
                          className="text-[9px] px-1.5 py-0.5 rounded-full font-bold"
                          style={{ backgroundColor: theme.colors.up + '15', color: theme.colors.up }}
                        >
                          {it.freeTier}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] font-mono" style={{ color: theme.colors.textSub }}>
                        {pb.daily_calls} {it.callsToday}
                      </span>
                    </div>
                  </div>

                  {!pb.is_free_tier && (
                    <>
                      <BudgetBar pct={pb.budget_pct_used} color={meta.color} />
                      <div className="flex items-center justify-between">
                        <span className="text-[10px]" style={{ color: theme.colors.textHint }}>
                          ${pb.monthly_spend_usd.toFixed(3)} / ${pb.monthly_limit_usd.toFixed(2)}
                        </span>
                        <span
                          className="text-[10px] font-semibold"
                          style={{ color: pb.budget_pct_used > 90 ? theme.colors.down : theme.colors.textSub }}
                        >
                          {pb.budget_pct_used.toFixed(0)}% {it.ofBudget}
                        </span>
                      </div>
                    </>
                  )}
                </div>
              )
            })}
          </div>

          {/* Edit limits / Daily info */}
          <div
            className="mt-3 pt-2 space-y-2"
            style={{ borderTop: `1px solid ${theme.colors.border}20` }}
          >
            {editing ? (
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-[10px]" style={{ color: theme.colors.textHint }}>{it.dailyLimit} (per provider)</span>
                  <input
                    type="number"
                    step="0.25"
                    min="0.25"
                    max="10"
                    value={limits.daily_limit}
                    onChange={(e) => setLimits({ ...limits, daily_limit: parseFloat(e.target.value) || 0.25 })}
                    className="w-20 text-right text-[11px] rounded px-2 py-0.5 outline-none"
                    style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.text, border: `1px solid ${theme.colors.border}` }}
                  />
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-[10px]" style={{ color: theme.colors.textHint }}>Claude {it.monthlyLimit}</span>
                  <input
                    type="number"
                    step="0.50"
                    min="0"
                    max="50"
                    value={limits.claude_monthly}
                    onChange={(e) => setLimits({ ...limits, claude_monthly: parseFloat(e.target.value) || 0 })}
                    className="w-20 text-right text-[11px] rounded px-2 py-0.5 outline-none"
                    style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.text, border: `1px solid ${theme.colors.border}` }}
                  />
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-[10px]" style={{ color: theme.colors.textHint }}>Grok {it.monthlyLimit}</span>
                  <input
                    type="number"
                    step="0.50"
                    min="0"
                    max="50"
                    value={limits.grok_monthly}
                    onChange={(e) => setLimits({ ...limits, grok_monthly: parseFloat(e.target.value) || 0 })}
                    className="w-20 text-right text-[11px] rounded px-2 py-0.5 outline-none"
                    style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.text, border: `1px solid ${theme.colors.border}` }}
                  />
                </div>
                <div className="flex gap-2 justify-end">
                  <Button variant="secondary" onClick={() => setEditing(false)}>{it.cancel}</Button>
                  <Button onClick={handleSave} disabled={saving}>{saving ? '...' : it.save}</Button>
                </div>
              </div>
            ) : (
              <div className="flex items-center justify-between">
                <span className="text-[10px]" style={{ color: theme.colors.textHint }}>
                  {it.dailyLimit}: ${budget.daily_limit_usd.toFixed(2)} / provider
                </span>
                <button
                  onClick={() => setEditing(true)}
                  className="text-[10px] font-semibold"
                  style={{ color: theme.colors.primary }}
                >
                  {it.editLimits}
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </Card>
  )
}

function IntegrationCard({ name, integration }: { name: string; integration: Integration }) {
  const theme = useTheme()
  const toast = useToast()
  const it = useI18nStore((s) => s.t).integrations
  const getMeta = useMeta()
  const meta = getMeta(name)
  const Icon = meta.icon
  const [pinging, setPinging] = useState(false)

  const handlePing = async () => {
    if (name !== 'telegram' || pinging) return
    setPinging(true)
    try {
      const res = await client.post('/health/ping-telegram')
      toast.show((res.data as { status: string }).status === 'sent' ? it.messageSent : it.pingFailed, (res.data as { status: string }).status === 'sent' ? 'success' : 'error')
    } catch {
      toast.show(it.failedToPing, 'error')
    }
    setPinging(false)
  }

  return (
    <Card>
      <div className="flex items-start gap-4">
        <div
          className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0"
          style={{ backgroundColor: meta.color + '15' }}
        >
          <Icon size={20} style={{ color: meta.color }} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between mb-1">
            <h3 className="text-sm font-bold" style={{ color: theme.colors.text }}>{meta.name}</h3>
            <StatusBadge status={integration.status} ok={integration.ok} />
          </div>
          <p className="text-[11px] mb-2" style={{ color: theme.colors.textSub }}>{meta.description}</p>

          {/* Details */}
          <div className="space-y-1">
            {integration.model && (
              <div className="flex items-center justify-between">
                <span className="text-[10px]" style={{ color: theme.colors.textHint }}>{it.model}</span>
                <span className="text-[10px] font-mono" style={{ color: theme.colors.text }}>{integration.model}</span>
              </div>
            )}
            {integration.detail && (
              <div
                className="text-[10px] rounded-lg px-2.5 py-1.5 mt-1"
                style={{
                  backgroundColor: integration.ok ? theme.colors.up + '08' : theme.colors.down + '08',
                  color: integration.ok ? theme.colors.up : theme.colors.down,
                  border: `1px solid ${integration.ok ? theme.colors.up : theme.colors.down}15`,
                }}
              >
                {integration.detail}
              </div>
            )}
          </div>

          {/* Actions */}
          {name === 'telegram' && integration.ok && (
            <div className="mt-2">
              <Button variant="secondary" onClick={handlePing} disabled={pinging}>
                {pinging ? it.sending : it.sendTest}
              </Button>
            </div>
          )}
        </div>
      </div>
    </Card>
  )
}

export default function IntegrationsPage() {
  const theme = useTheme()
  const it = useI18nStore((s) => s.t).integrations

  const { data, isLoading, refetch, isFetching } = useQuery<IntegrationsData>({
    queryKey: ['health', 'integrations'],
    queryFn: async () => {
      const res = await client.get<IntegrationsData>('/health/integrations')
      return res.data
    },
    staleTime: 0,
  })

  const { data: budget, isLoading: budgetLoading } = useQuery<BudgetData>({
    queryKey: ['health', 'budget'],
    queryFn: async () => {
      const res = await client.get<BudgetData>('/health/budget')
      return res.data
    },
    staleTime: 30_000,
  })

  const entries = data ? Object.entries(data.integrations) : []
  const okCount = entries.filter(([, v]) => v.ok).length
  const totalCount = entries.length

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: theme.colors.text }}>{it.title}</h1>
          {data && (
            <p className="text-sm mt-1" style={{ color: theme.colors.textSub }}>
              {it.servicesHealthy.replace('{ok}', String(okCount)).replace('{total}', String(totalCount))}
            </p>
          )}
        </div>
        <Button
          variant="secondary"
          onClick={() => refetch()}
          disabled={isFetching}
        >
          <span className="flex items-center gap-1.5">
            <RefreshCw size={14} className={isFetching ? 'animate-spin' : ''} />
            {isFetching ? it.checking : it.refresh}
          </span>
        </Button>
      </div>

      {/* Budget Card */}
      {budgetLoading ? (
        <Skeleton width="100%" height={200} borderRadius={14} />
      ) : budget ? (
        <BudgetCard budget={budget} />
      ) : null}

      {/* Integration Cards */}
      {isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} width="100%" height={120} borderRadius={14} />
          ))}
        </div>
      ) : (
        <div className="space-y-3">
          {entries.map(([name, integration]) => (
            <IntegrationCard key={name} name={name} integration={integration} />
          ))}
        </div>
      )}
    </div>
  )
}
