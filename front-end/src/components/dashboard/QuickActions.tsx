'use client'

import { useMemo } from 'react'
import Link from 'next/link'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useAllSignals } from '@/hooks/useSignals'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { Skeleton } from '@/components/ui/Skeleton'
import { ShieldCheck, AlertTriangle } from 'lucide-react'
import type { Signal } from '@/types/signal'

function getRiskLevel(signal: Signal): 'low' | 'medium' | 'high' {
  if (signal.bucket === 'SAFE_INCOME' && signal.score >= 75) return 'low'
  if (signal.score >= 70 && signal.risk_reward && signal.risk_reward >= 2) return 'low'
  if (signal.score >= 60) return 'medium'
  return 'high'
}

function RiskBadge({ level }: { level: 'low' | 'medium' | 'high' }) {
  const theme = useTheme()
  const tt = useI18nStore((s) => s.t)
  const colors: Record<string, string> = {
    low: theme.colors.up,
    medium: theme.colors.warning,
    high: theme.colors.down,
  }
  const labels: Record<string, string> = {
    low: tt.overview.low,
    medium: tt.overview.medium,
    high: tt.overview.high,
  }
  return (
    <span
      className="text-[9px] font-bold px-1.5 py-0.5 rounded"
      style={{ backgroundColor: colors[level] + '18', color: colors[level] }}
    >
      {labels[level]}
    </span>
  )
}

function MiniRow({ signal }: { signal: Signal }) {
  const theme = useTheme()
  const risk = getRiskLevel(signal)
  return (
    <Link href={`/signals/${signal.symbol}`}>
      <div
        className="flex items-center justify-between py-2 px-1 rounded-lg transition-all hover:opacity-80"
        style={{ borderBottom: `1px solid ${theme.colors.border}` }}
      >
        <div className="flex items-center gap-2.5">
          <span className="text-[13px] font-semibold w-20" style={{ color: theme.colors.text }}>{signal.symbol}</span>
          <Badge variant={signal.action === 'BUY' ? 'buy' : signal.action === 'SELL' ? 'sell' : signal.action === 'AVOID' ? 'avoid' : 'hold'}>
            {signal.action}
          </Badge>
          <RiskBadge level={risk} />
        </div>
        <div className="flex items-center gap-3">
          <span className="text-[12px] font-semibold tabular-nums" style={{ color: theme.colors.text }}>
            {signal.score}
          </span>
          <span className="text-[11px] tabular-nums" style={{ color: theme.colors.textSub }}>
            {signal.price_at_signal ? `$${Number(signal.price_at_signal).toFixed(2)}` : '--'}
          </span>
        </div>
      </div>
    </Link>
  )
}

export function QuickActions() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const { data: signals, isLoading } = useAllSignals({ limit: 200 })

  // Safe to buy: BUY signals sorted by score desc, prefer SAFE_INCOME
  const safeToBuy = useMemo(() => {
    if (!signals?.length) return []
    return signals
      .filter((s) => s.action === 'BUY' && s.score >= 65)
      .sort((a, b) => {
        const aRisk = getRiskLevel(a) === 'low' ? 0 : getRiskLevel(a) === 'medium' ? 1 : 2
        const bRisk = getRiskLevel(b) === 'low' ? 0 : getRiskLevel(b) === 'medium' ? 1 : 2
        return aRisk - bRisk || b.score - a.score
      })
      .slice(0, 5)
  }, [signals])

  // Must sell: SELL or AVOID signals, plus WEAKENING signals
  const mustSell = useMemo(() => {
    if (!signals?.length) return []
    return signals
      .filter((s) => s.action === 'SELL' || s.action === 'AVOID' || s.status === 'WEAKENING')
      .sort((a, b) => a.score - b.score)
      .slice(0, 5)
  }, [signals])

  if (isLoading) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card><Skeleton width="100%" height={120} /></Card>
        <Card><Skeleton width="100%" height={120} /></Card>
      </div>
    )
  }

  if (!signals?.length) return null

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {/* Safe to Buy */}
      <Card>
        <div className="flex items-center gap-2 mb-3">
          <ShieldCheck size={16} style={{ color: theme.colors.up }} />
          <p className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: theme.colors.textSub }}>
            {t.overview.safeToBuy}
          </p>
        </div>
        {safeToBuy.length > 0 ? (
          <div>
            {safeToBuy.map((s) => <MiniRow key={s.id} signal={s} />)}
          </div>
        ) : (
          <p className="text-xs" style={{ color: theme.colors.textHint }}>
            {t.overview.safeToBuyDesc}
          </p>
        )}
      </Card>

      {/* Must Sell */}
      <Card>
        <div className="flex items-center gap-2 mb-3">
          <AlertTriangle size={16} style={{ color: theme.colors.down }} />
          <p className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: theme.colors.textSub }}>
            {t.overview.mustSell}
          </p>
        </div>
        {mustSell.length > 0 ? (
          <div>
            {mustSell.map((s) => <MiniRow key={s.id} signal={s} />)}
          </div>
        ) : (
          <p className="text-xs" style={{ color: theme.colors.textHint }}>
            {t.overview.mustSellDesc}
          </p>
        )}
      </Card>
    </div>
  )
}
