'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { Badge } from '@/components/ui/Badge'
import { ScoreRing } from '@/components/ui/ScoreRing'
import { SparkLine } from '@/components/ui/SparkLine'
import { ProgressBar } from '@/components/ui/ProgressBar'
import { Button } from '@/components/ui/Button'
import { Skeleton } from '@/components/ui/Skeleton'
import { useWatchlist, useAddTicker, useRemoveTicker } from '@/hooks/useWatchlist'
import { useToast } from '@/hooks/useToast'
import { ChevronDown, Star, ExternalLink } from 'lucide-react'
import type { Signal } from '@/types/signal'

interface SignalCardProps {
  signal: Signal
  defaultExpanded?: boolean
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
  const t = useI18nStore((s) => s.t)
  const [expanded, setExpanded] = useState(defaultExpanded)
  const { data: watchlist } = useWatchlist()
  const addTicker = useAddTicker()
  const removeTicker = useRemoveTicker()
  const toast = useToast()
  const isWatchlisted = watchlist?.some((w) => w.symbol === signal.symbol) ?? false

  const handleToggle = () => setExpanded((prev) => !prev)
  const stopProp = (e: React.MouseEvent) => e.stopPropagation()

  const price = signal.current_price ?? signal.price_at_signal
  const isPositive = signal.change_pct !== null ? signal.change_pct >= 0 : signal.score >= 60
  const changeColor = isPositive ? theme.colors.up : theme.colors.down

  // Sentiment is real only if grok_data has confidence > 0
  const grokConfidence = (signal.grok_data as Record<string, unknown>)?.confidence as number | undefined
  const hasSentiment = signal.sentiment_score !== null && grokConfidence !== undefined && grokConfidence > 0

  // Scoring weights for display
  const isHighRisk = signal.bucket === 'HIGH_RISK'
  const weights = isHighRisk
    ? [
        { label: 'Sentiment (X/Twitter)', pct: 35, color: theme.colors.primary },
        { label: 'Catalyst', pct: 30, color: theme.colors.up },
        { label: 'Technical momentum', pct: 25, color: theme.colors.warning },
        { label: 'Fundamentals', pct: 10, color: theme.colors.textSub },
      ]
    : [
        { label: 'Dividend reliability', pct: 35, color: theme.colors.up },
        { label: 'Fundamental health', pct: 30, color: theme.colors.primary },
        { label: 'Macro conditions', pct: 25, color: theme.colors.warning },
        { label: 'Sentiment', pct: 10, color: theme.colors.textSub },
      ]

  return (
    <div
      className="rounded-2xl overflow-hidden cursor-pointer transition-all"
      style={{
        backgroundColor: theme.colors.surface,
        border: `1px solid ${theme.colors.border}`,
        boxShadow: theme.isDark ? '0 1px 4px rgba(0,0,0,0.2)' : '0 1px 4px rgba(0,0,0,0.04)',
      }}
      onClick={handleToggle}
    >
      <div className="px-4 pt-4 pb-3">
        {/* Row 1: Ticker + Watchlist star + Price */}
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-3">
            <div
              className="w-10 h-10 rounded-xl flex items-center justify-center text-[11px] font-bold tracking-tight"
              style={{ backgroundColor: theme.colors.primary + '12', color: theme.colors.primary }}
            >
              {signal.symbol.slice(0, 4)}
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-[15px] font-semibold" style={{ color: theme.colors.text }}>
                  {signal.symbol}
                </span>
                {signal.is_gem && (
                  <span
                    className="text-[9px] font-bold px-1.5 py-0.5 rounded-md"
                    style={{ backgroundColor: theme.colors.up + '18', color: theme.colors.up }}
                  >
                    GEM
                  </span>
                )}
                <button
                  onClick={(e) => {
                    stopProp(e)
                    if (isWatchlisted) {
                      removeTicker.mutate(signal.symbol, {
                        onSuccess: () => toast.show(`${signal.symbol} removed from watchlist`, 'info'),
                        onError: (err) => toast.show(err?.message || 'Failed', 'error'),
                      })
                    } else {
                      addTicker.mutate(signal.symbol, {
                        onSuccess: () => toast.show(`${signal.symbol} added to watchlist`, 'success'),
                        onError: (err) => toast.show(err?.message || 'Failed', 'error'),
                      })
                    }
                  }}
                  disabled={addTicker.isPending || removeTicker.isPending}
                  className="p-0.5 rounded transition-opacity hover:opacity-70"
                  title={isWatchlisted ? 'Remove from watchlist' : t.signal.addToWatchlist}
                >
                  <Star
                    size={14}
                    fill={isWatchlisted ? theme.colors.warning : 'none'}
                    style={{ color: isWatchlisted ? theme.colors.warning : theme.colors.textHint }}
                  />
                </button>
              </div>
              <span className="text-[12px]" style={{ color: theme.colors.textSub }}>
                {signal.exchange ?? (signal.asset_type === 'CRYPTO' ? t.signal.crypto : 'Equity')}
              </span>
            </div>
          </div>

          <div className="text-right flex items-center gap-2.5">
            <SparkLine positive={isPositive} width={48} height={22} />
            <div>
              <p className="text-[16px] font-semibold tabular-nums" style={{ color: theme.colors.text }}>
                {formatPrice(price)}
              </p>
              <p className="text-[12px] font-semibold tabular-nums" style={{ color: changeColor }}>
                {signal.change_pct !== null && signal.change_pct !== undefined
                  ? `${signal.change_pct >= 0 ? '+' : ''}${signal.change_pct.toFixed(2)}%`
                  : `${signal.score}/100`}
              </p>
            </div>
          </div>
        </div>

        {/* Row 2: Metrics + Badges */}
        <div className="flex items-center gap-4 mt-3">
          <ScoreRing score={signal.score} size={38} />
          <div className="flex items-center gap-4 flex-1 min-w-0">
            <div>
              <p className="text-[10px] uppercase tracking-wide" style={{ color: theme.colors.textHint }}>{t.signal.target}</p>
              <p className="text-[13px] font-semibold tabular-nums" style={{ color: theme.colors.up }}>{formatPrice(signal.target_price)}</p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-wide" style={{ color: theme.colors.textHint }}>{t.signal.stopLoss}</p>
              <p className="text-[13px] font-semibold tabular-nums" style={{ color: theme.colors.down }}>{formatPrice(signal.stop_loss)}</p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-wide" style={{ color: theme.colors.textHint }}>{t.signal.riskReward}</p>
              <p className="text-[13px] font-semibold tabular-nums" style={{ color: theme.colors.primary }}>{signal.risk_reward ? `${signal.risk_reward.toFixed(1)}x` : '--'}</p>
            </div>
          </div>
          <div className="flex items-center gap-1.5 shrink-0">
            <Badge variant={signal.action === 'BUY' ? 'buy' : signal.action === 'SELL' ? 'sell' : signal.action === 'AVOID' ? 'avoid' : 'hold'}>
              {signal.action}
            </Badge>
            <Badge variant={getStatusVariant(signal.status)}>{signal.status}</Badge>
            {signal.account_recommendation && (
              <Badge variant={signal.account_recommendation === 'TFSA' ? 'safe' : 'risk'}>
                {signal.account_recommendation}
              </Badge>
            )}
          </div>
        </div>

        <div className="flex justify-center mt-2">
          <ChevronDown
            size={14}
            className="transition-transform duration-200"
            style={{ color: theme.colors.textHint, transform: expanded ? 'rotate(180deg)' : 'rotate(0deg)' }}
          />
        </div>
      </div>

      {/* Expanded */}
      {expanded && (
        <div className="px-4 pb-4" style={{ borderTop: `1px solid ${theme.colors.border}` }}>
          <div className="pt-3 space-y-3">
            {/* Reasoning */}
            {signal.reasoning && (
              <div>
                <p className="text-[10px] uppercase tracking-wide mb-1" style={{ color: theme.colors.textHint }}>Why this signal</p>
                <p className="text-[13px] leading-relaxed" style={{ color: theme.colors.textSub }}>{signal.reasoning}</p>
              </div>
            )}

            {/* Scoring breakdown */}
            <div>
              <p className="text-[10px] uppercase tracking-wide mb-2" style={{ color: theme.colors.textHint }}>
                Score breakdown ({isHighRisk ? t.signal.highRisk : t.signal.safeIncome} model)
              </p>
              <div className="space-y-1.5">
                {weights.map((w) => (
                  <div key={w.label} className="flex items-center gap-2">
                    <span className="text-[11px] w-[140px] shrink-0" style={{ color: theme.colors.textSub }}>{w.label}</span>
                    <div className="flex-1"><ProgressBar value={w.pct} color={w.color} height={3} /></div>
                    <span className="text-[11px] font-semibold w-8 text-right tabular-nums" style={{ color: w.color }}>{w.pct}%</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Sentiment — only real data */}
            {hasSentiment && (
              <div>
                <div className="flex justify-between items-center mb-1">
                  <span className="text-[10px] uppercase tracking-wide" style={{ color: theme.colors.textHint }}>
                    X/Twitter {t.signal.sentiment}
                  </span>
                  <span className="text-[11px] font-semibold" style={{ color: theme.colors.text }}>
                    {t.signal.bullish.replace('{score}', String(signal.sentiment_score))}
                  </span>
                </div>
                <ProgressBar value={signal.sentiment_score!} color={isHighRisk ? theme.colors.primary : theme.colors.up} height={3} />
              </div>
            )}

            {/* Catalyst + GEM reason */}
            {(signal.catalyst || signal.gem_reason) && (
              <div className="flex flex-wrap gap-1.5">
                {signal.catalyst && <Badge variant="buy">{signal.catalyst}</Badge>}
                {signal.gem_reason && <Badge variant="gem">{signal.gem_reason}</Badge>}
              </div>
            )}

            {/* Extra metrics */}
            <div className="grid grid-cols-3 gap-3">
              <div>
                <p className="text-[10px] uppercase tracking-wide" style={{ color: theme.colors.textHint }}>{t.signal.confidence}</p>
                <p className="text-[13px] font-semibold" style={{ color: theme.colors.primary }}>{signal.confidence}%</p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wide" style={{ color: theme.colors.textHint }}>{t.signal.priceAtSignal}</p>
                <p className="text-[13px] font-semibold" style={{ color: theme.colors.text }}>{formatPrice(signal.price_at_signal)}</p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wide" style={{ color: theme.colors.textHint }}>{t.signal.entryWindow}</p>
                <p className="text-[13px] font-semibold" style={{ color: theme.colors.text }}>{signal.entry_window ?? t.signal.tbd}</p>
              </div>
            </div>

            {/* View full details */}
            <div onClick={stopProp}>
              <Link href={`/signals/${signal.symbol}`}>
                <Button fullWidth variant="secondary">
                  <span className="flex items-center gap-2 justify-center">
                    <ExternalLink size={14} />
                    {t.signal.viewFullAnalysis}
                  </span>
                </Button>
              </Link>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export function SignalCardSkeleton() {
  return (
    <div className="rounded-2xl overflow-hidden" style={{ padding: '16px' }}>
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <Skeleton width={40} height={40} borderRadius={12} />
          <div className="space-y-1.5">
            <Skeleton width={72} height={14} />
            <Skeleton width={48} height={10} />
          </div>
        </div>
        <div className="space-y-1.5 text-right">
          <Skeleton width={64} height={14} />
          <Skeleton width={48} height={10} />
        </div>
      </div>
      <div className="flex items-center gap-4 mt-3">
        <Skeleton width={38} height={38} borderRadius={19} />
        <Skeleton width={180} height={14} />
        <div className="flex gap-1.5 ml-auto">
          <Skeleton width={42} height={20} borderRadius={10} />
          <Skeleton width={64} height={20} borderRadius={10} />
        </div>
      </div>
    </div>
  )
}
