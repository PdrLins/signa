'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTheme } from '@/hooks/useTheme'
import { Card } from '@/components/ui/Card'
import { Skeleton } from '@/components/ui/Skeleton'
import { client } from '@/lib/api'
import { useI18nStore } from '@/store/i18nStore'
import { useToast } from '@/hooks/useToast'
import { Database, Send, Brain, Zap, Clock } from 'lucide-react'

interface Integration {
  status: string
  ok: boolean
  detail?: string
  model?: string
}

interface IntegrationsResponse {
  status: string
  integrations: Record<string, Integration>
}

const LABELS: Record<string, { icon: typeof Send; pingable?: boolean }> = {
  supabase: { icon: Database },
  telegram: { icon: Send, pingable: true },
  claude: { icon: Brain },
  grok: { icon: Zap },
  scheduler: { icon: Clock },
}

function useIntegrations() {
  return useQuery<IntegrationsResponse>({
    queryKey: ['health', 'integrations'],
    queryFn: async () => {
      const res = await client.get<IntegrationsResponse>('/health/integrations')
      return res.data
    },
    refetchInterval: 60 * 1000,
    staleTime: 30 * 1000,
  })
}

export function TelegramStatus() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const toast = useToast()
  const { data, isLoading } = useIntegrations()
  const [pinging, setPinging] = useState(false)

  const getName = (key: string): string => {
    const names: Record<string, string> = {
      supabase: t.integrations.supabase,
      telegram: t.integrations.telegram,
      claude: t.integrations.claude,
      grok: t.integrations.grok,
      scheduler: t.integrations.scheduler,
    }
    return names[key] || key
  }

  const handlePing = async (key: string) => {
    if (key !== 'telegram' || pinging) return
    setPinging(true)
    try {
      const res = await client.post<{ status: string; message: string }>('/health/ping-telegram')
      if (res.data.status === 'sent') {
        toast.show(t.integrations.pingSent, 'success')
      } else {
        toast.show(t.integrations.pingFailed, 'error')
      }
    } catch {
      toast.show(t.integrations.pingFailed, 'error')
    }
    setPinging(false)
  }

  if (isLoading) {
    return <Card><Skeleton width="100%" height={80} /></Card>
  }
  if (!data) return null

  const entries = Object.entries(data.integrations)

  return (
    <Card>
      <div className="flex items-center justify-between mb-3">
        <p className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: theme.colors.textSub }}>
          {t.integrations.title}
        </p>
        <span
          className="text-[10px] font-bold px-1.5 py-0.5 rounded"
          style={{
            backgroundColor: data.status === 'healthy' ? theme.colors.up + '20' : theme.colors.down + '20',
            color: data.status === 'healthy' ? theme.colors.up : theme.colors.down,
          }}
        >
          {data.status === 'healthy' ? t.integrations.allOk : t.integrations.degraded}
        </span>
      </div>
      <div className="space-y-2">
        {entries.map(([key, integration]) => {
          const label = LABELS[key] || { icon: Zap }
          const Icon = label.icon
          const color = integration.ok ? theme.colors.up : theme.colors.down
          const isPingable = label.pingable && integration.ok

          return (
            <div
              key={key}
              className="flex items-center justify-between"
              style={{ cursor: isPingable ? 'pointer' : 'default' }}
              onClick={() => isPingable && handlePing(key)}
              title={isPingable ? t.integrations.pingTooltip : undefined}
            >
              <div className="flex items-center gap-2">
                <Icon
                  size={14}
                  style={{
                    color: integration.ok ? theme.colors.textSub : theme.colors.down,
                    animation: pinging && key === 'telegram' ? 'pulse 1s infinite' : 'none',
                  }}
                />
                <span className="text-xs" style={{ color: theme.colors.text }}>{getName(key)}</span>
                {isPingable && (
                  <span className="text-[9px]" style={{ color: theme.colors.textHint }}>
                    {t.integrations.tapToPing}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: color }} />
                <span className="text-[10px]" style={{ color }}>{integration.status}</span>
              </div>
            </div>
          )
        })}
      </div>
    </Card>
  )
}
