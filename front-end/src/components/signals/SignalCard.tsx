'use client'

import { useState } from 'react'
import { useTheme } from '@/hooks/useTheme'
import { Badge } from '@/components/ui/Badge'
import { ScoreRing } from '@/components/ui/ScoreRing'
import { SparkLine } from '@/components/ui/SparkLine'
import { ProgressBar } from '@/components/ui/ProgressBar'
import { Button } from '@/components/ui/Button'
import { Skeleton } from '@/components/ui/Skeleton'
import { useAddTicker } from '@/hooks/useWatchlist'
import type { Signal } from '@/types/signal'

interface SignalCardProps {
  signal: Signal
  defaultExpanded?: boolean
}

function getBucketVariant(bucket: string | null): 'risk' | 'safe' | 'hold' {
  if (bucket === 'HIGH_RISK') return 'risk'
  if (bucket === 'SAFE_INCOME') return 'safe'
  return 'hold'
}

function getStatusVariant(status: string) {
  const map: Record<string, 'confirmed' | 'weakening' | 'cancelled' | 'upgraded'> = {
    CONFIRMED: 'confirmed',
    WEAKENING: 'weakening',
    CANCELLED: 'cancelled',
    UPGRADED: 'upgraded',
  }
  return map[status] || 'hold'
}

function formatPrice(value: number | null): string {
  if (value === null) return '--'
  return `$${value.toFixed(2)}`
}

export function SignalCard({ signal, defaultExpanded = false }: SignalCardProps) {
  const theme = useTheme()
  const [expanded, setExpanded] = useState(defaultExpanded)
  const addTicker = useAddTicker()

  const stripe =
    signal.bucket === 'HIGH_RISK' ? theme.colors.stripeRisk : theme.colors.stripeSafe

  const handleToggle = () => setExpanded((prev) => !prev)
  const stopProp = (e: React.MouseEvent) => e.stopPropagation()

  return (
    <div
      className="rounded-[14px] overflow-hidden cursor-pointer transition-all"
      style={{
        backgroundColor: theme.colors.surface,
        border: `0.5px solid ${theme.colors.border}`,
        boxShadow: theme.isDark ? '0 2px 10px rgba(0,0,0,0.3)' : '0 2px 10px rgba(0,0,0,0.06)',
      }}
      onClick={handleToggle}
    >
      {/* Stripe */}
      <div className="h-[3px] w-full" style={{ background: stripe }} />

      <div className="p-4">
        {/* Header */}
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <div
              className="w-11 h-11 rounded-[11px] flex items-center justify-center text-xs font-bold"
              style={{
                backgroundColor: theme.colors.primary + '18',
                color: theme.colors.primary,
              }}
            >
              {signal.symbol.slice(0, 4)}
            </div>
            <div>
              <p className="text-base font-bold leading-tight" style={{ color: theme.colors.text }}>
                {signal.symbol}
              </p>
              <p className="text-xs" style={{ color: theme.colors.textSub }}>
                {signal.action} · {signal.bucket === 'HIGH_RISK' ? 'High Risk' : signal.bucket === 'SAFE_INCOME' ? 'Safe Income' : 'Unclassified'}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <SparkLine positive={signal.score >= 60} width={52} height={24} />
            <div className="text-right">
              <p className="text-[17px] font-bold" style={{ color: theme.colors.text }}>
                {formatPrice(signal.current_price ?? signal.price_at_signal)}
              </p>
              {signal.change_pct !== null && signal.change_pct !== undefined ? (
                <p
                  className="text-[13px] font-bold"
                  style={{ color: signal.change_pct >= 0 ? theme.colors.up : theme.colors.down }}
                >
                  {signal.change_pct >= 0 ? '+' : ''}{signal.change_pct.toFixed(2)}%
                </p>
              ) : (
                <p
                  className="text-[13px] font-bold"
                  style={{ color: signal.score >= 60 ? theme.colors.up : theme.colors.down }}
                >
                  Score {signal.score}
                </p>
              )}
            </div>
          </div>
        </div>

        {/* Badges */}
        <div className="flex flex-wrap gap-1.5 mb-3">
          <Badge variant={getBucketVariant(signal.bucket)}>
            {signal.bucket === 'HIGH_RISK' ? 'High risk' : signal.bucket === 'SAFE_INCOME' ? 'Safe income' : 'Unclassified'}
          </Badge>
          {signal.catalyst && <Badge variant="buy">{signal.catalyst}</Badge>}
          <Badge variant={getStatusVariant(signal.status)}>{signal.status}</Badge>
          {signal.is_gem && <Badge variant="gem">GEM</Badge>}
        </div>

        {/* Score + Mini Stats */}
        <div className="flex items-center gap-3 mb-3">
          <ScoreRing score={signal.score} size={50} />
          <div className="flex-1 grid grid-cols-3 gap-1.5">
            {[
              { label: 'Target', value: formatPrice(signal.target_price), color: theme.colors.up },
              { label: 'Stop Loss', value: formatPrice(signal.stop_loss), color: theme.colors.down },
              { label: 'Risk/Rew.', value: signal.risk_reward ? `${signal.risk_reward.toFixed(1)}x` : '--', color: theme.colors.primary },
            ].map((stat) => (
              <div
                key={stat.label}
                className="rounded-lg px-2 py-1.5 text-center"
                style={{ backgroundColor: theme.colors.surfaceAlt }}
              >
                <p className="text-[10px]" style={{ color: theme.colors.textSub }}>
                  {stat.label}
                </p>
                <p className="text-xs font-bold" style={{ color: stat.color }}>
                  {stat.value}
                </p>
              </div>
            ))}
          </div>
        </div>

        {/* Sentiment */}
        {signal.sentiment_score !== null && (
          <div className="mb-3">
            <div className="flex justify-between items-center mb-1">
              <span className="text-[11px]" style={{ color: theme.colors.textSub }}>
                Sentiment
              </span>
              <span className="text-[11px] font-semibold" style={{ color: theme.colors.text }}>
                {signal.sentiment_score}% bullish
              </span>
            </div>
            <ProgressBar
              value={signal.sentiment_score}
              color={signal.bucket === 'HIGH_RISK' ? theme.colors.primary : theme.colors.up}
            />
          </div>
        )}

        {/* Reasoning */}
        {signal.reasoning && (
          <div
            className="rounded-[9px] px-3 py-2.5 mb-2"
            style={{ backgroundColor: theme.colors.surfaceAlt }}
          >
            <p
              className="text-[13px] leading-[1.55]"
              style={{ color: theme.colors.textSub }}
            >
              {signal.reasoning}
            </p>
          </div>
        )}

        {/* Expand hint */}
        {!expanded && (
          <p className="text-center text-[9px] mt-1" style={{ color: theme.colors.textHint }}>
            More details ↓
          </p>
        )}

        {/* Expanded section */}
        {expanded && (
          <div className="mt-3">
            <div className="h-px w-full mb-3" style={{ backgroundColor: theme.colors.border }} />

            {/* Confidence + extra data */}
            <div className="grid grid-cols-2 gap-1.5 mb-3">
              <div className="rounded-lg px-2 py-1.5 text-center" style={{ backgroundColor: theme.colors.surfaceAlt }}>
                <p className="text-[10px]" style={{ color: theme.colors.textSub }}>Confidence</p>
                <p className="text-xs font-bold" style={{ color: theme.colors.primary }}>{signal.confidence}%</p>
              </div>
              <div className="rounded-lg px-2 py-1.5 text-center" style={{ backgroundColor: theme.colors.surfaceAlt }}>
                <p className="text-[10px]" style={{ color: theme.colors.textSub }}>Price at Signal</p>
                <p className="text-xs font-bold" style={{ color: theme.colors.text }}>{formatPrice(signal.price_at_signal)}</p>
              </div>
              <div className="rounded-lg px-2 py-1.5 text-center" style={{ backgroundColor: theme.colors.surfaceAlt }}>
                <p className="text-[10px]" style={{ color: theme.colors.textSub }}>Entry Window</p>
                <p className="text-xs font-bold" style={{ color: theme.colors.text }}>{signal.entry_window ?? 'TBD'}</p>
              </div>
              {signal.gem_reason && (
                <div className="rounded-lg px-2 py-1.5 text-center" style={{ backgroundColor: theme.colors.surfaceAlt }}>
                  <p className="text-[10px]" style={{ color: theme.colors.textSub }}>GEM Reason</p>
                  <p className="text-xs font-bold" style={{ color: theme.colors.up }}>{signal.gem_reason}</p>
                </div>
              )}
            </div>

            {/* Actions */}
            <div className="flex gap-2" onClick={stopProp}>
              <a
                href="https://my.wealthsimple.com"
                target="_blank"
                rel="noopener noreferrer"
                className="flex-1"
                onClick={stopProp}
              >
                <Button fullWidth>Open Wealthsimple</Button>
              </a>
              <div className="flex-1">
                <Button
                  variant="secondary"
                  fullWidth
                  onClick={(e) => {
                    stopProp(e)
                    addTicker.mutate(signal.symbol)
                  }}
                  disabled={addTicker.isPending}
                >
                  {addTicker.isPending ? 'Adding...' : 'Add to watchlist'}
                </Button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export function SignalCardSkeleton() {
  return (
    <div className="space-y-3 p-4">
      <Skeleton width="100%" height={3} borderRadius={0} />
      <div className="flex items-center gap-3">
        <Skeleton width={44} height={44} borderRadius={11} />
        <div className="space-y-1.5 flex-1">
          <Skeleton width={80} height={14} />
          <Skeleton width={120} height={10} />
        </div>
      </div>
      <div className="flex gap-1.5">
        <Skeleton width={70} height={20} borderRadius={10} />
        <Skeleton width={60} height={20} borderRadius={10} />
        <Skeleton width={80} height={20} borderRadius={10} />
      </div>
      <div className="flex gap-3">
        <Skeleton width={50} height={50} borderRadius={25} />
        <div className="flex-1 grid grid-cols-3 gap-1.5">
          <Skeleton height={40} />
          <Skeleton height={40} />
          <Skeleton height={40} />
        </div>
      </div>
      <Skeleton width="100%" height={3} />
      <Skeleton width="100%" height={60} borderRadius={9} />
    </div>
  )
}
