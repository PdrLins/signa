'use client'

import { useParams } from 'next/navigation'
import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useToast } from '@/hooks/useToast'
import { useAddTicker } from '@/hooks/useWatchlist'
import { tickersApi, signalsApi } from '@/lib/api'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { ScoreRing } from '@/components/ui/ScoreRing'
import { ProgressBar } from '@/components/ui/ProgressBar'
import { Skeleton } from '@/components/ui/Skeleton'
import { ArrowLeft, Star, TrendingUp, TrendingDown } from 'lucide-react'

function formatPrice(v: number | null | undefined): string {
  if (v === null || v === undefined) return '--'
  return `$${Number(v).toFixed(2)}`
}

export default function TickerDetailPage() {
  const params = useParams()
  const ticker = (params.ticker as string)?.toUpperCase() ?? ''
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const toast = useToast()
  const addTicker = useAddTicker()

  const { data: detail, isLoading: loadingDetail } = useQuery({
    queryKey: ['ticker', ticker],
    queryFn: () => tickersApi.getDetail(ticker),
    enabled: !!ticker,
  })

  const { data: signalHistory } = useQuery({
    queryKey: ['signals', ticker, 'history'],
    queryFn: async () => {
      const res = await signalsApi.getByTicker(ticker, 10)
      return res.signals
    },
    enabled: !!ticker,
  })

  const latest = signalHistory?.[0]
  const fundamentals = detail?.fundamentals as Record<string, unknown> | undefined
  const currentPrice = detail?.current_price as number | undefined

  // Scoring weights
  const isHighRisk = latest?.bucket === 'HIGH_RISK'
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

  if (loadingDetail) {
    return (
      <div className="space-y-4 max-w-[720px]">
        <Skeleton width={200} height={28} />
        <Skeleton width="100%" height={200} borderRadius={14} />
        <Skeleton width="100%" height={150} borderRadius={14} />
      </div>
    )
  }

  return (
    <div className="space-y-4 max-w-[720px]">
      {/* Back + Header */}
      <div className="flex items-center gap-3">
        <Link href="/signals" className="p-1.5 rounded-lg transition-opacity hover:opacity-70" style={{ color: theme.colors.textSub }}>
          <ArrowLeft size={20} />
        </Link>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold" style={{ color: theme.colors.text }}>{ticker}</h1>
            {latest?.is_gem && (
              <span className="text-[10px] font-bold px-2 py-0.5 rounded-md" style={{ backgroundColor: theme.colors.up + '18', color: theme.colors.up }}>
                GEM
              </span>
            )}
            <button
              onClick={() => addTicker.mutate(ticker, {
                onSuccess: () => toast.show(`${ticker} added to watchlist`, 'success'),
                onError: (err) => toast.show(err?.message || 'Failed', 'error'),
              })}
              className="p-1 rounded transition-opacity hover:opacity-70"
              title={t.signal.addToWatchlist}
            >
              <Star size={18} style={{ color: theme.colors.textHint }} />
            </button>
          </div>
          <p className="text-sm" style={{ color: theme.colors.textSub }}>
            {detail?.exchange as string ?? ''} &middot; {detail?.asset_type as string ?? 'Equity'}
          </p>
        </div>
        <div className="text-right">
          <p className="text-2xl font-bold tabular-nums" style={{ color: theme.colors.text }}>
            {formatPrice(currentPrice ?? null)}
          </p>
        </div>
      </div>

      {/* Latest Signal */}
      {latest && (
        <Card>
          <div className="flex items-center justify-between mb-3">
            <p className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: theme.colors.textSub }}>Latest Signal</p>
            <div className="flex items-center gap-1.5">
              <Badge variant={latest.action === 'BUY' ? 'buy' : latest.action === 'SELL' ? 'sell' : latest.action === 'AVOID' ? 'avoid' : 'hold'}>
                {latest.action}
              </Badge>
              <Badge variant={latest.status === 'CONFIRMED' ? 'confirmed' : latest.status === 'WEAKENING' ? 'weakening' : latest.status === 'UPGRADED' ? 'upgraded' : 'cancelled'}>
                {latest.status}
              </Badge>
            </div>
          </div>

          <div className="flex items-center gap-4 mb-4">
            <ScoreRing score={latest.score} size={50} />
            <div className="grid grid-cols-3 gap-4 flex-1">
              <div>
                <p className="text-[10px] uppercase tracking-wide" style={{ color: theme.colors.textHint }}>{t.signal.target}</p>
                <p className="text-sm font-semibold" style={{ color: theme.colors.up }}>{formatPrice(latest.target_price)}</p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wide" style={{ color: theme.colors.textHint }}>{t.signal.stopLoss}</p>
                <p className="text-sm font-semibold" style={{ color: theme.colors.down }}>{formatPrice(latest.stop_loss)}</p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-wide" style={{ color: theme.colors.textHint }}>{t.signal.riskReward}</p>
                <p className="text-sm font-semibold" style={{ color: theme.colors.primary }}>{latest.risk_reward ? `${latest.risk_reward.toFixed(1)}x` : '--'}</p>
              </div>
            </div>
          </div>

          {/* Reasoning */}
          {latest.reasoning && (
            <div className="mb-3">
              <p className="text-[10px] uppercase tracking-wide mb-1" style={{ color: theme.colors.textHint }}>Why this signal</p>
              <p className="text-sm leading-relaxed" style={{ color: theme.colors.textSub }}>{latest.reasoning}</p>
            </div>
          )}

          {/* Score breakdown */}
          <div>
            <p className="text-[10px] uppercase tracking-wide mb-2" style={{ color: theme.colors.textHint }}>
              Score breakdown ({isHighRisk ? 'High Risk' : 'Safe Income'} model)
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
        </Card>
      )}

      {/* Fundamentals */}
      {fundamentals && Object.keys(fundamentals).length > 0 && (
        <Card>
          <p className="text-[11px] font-semibold uppercase tracking-wide mb-3" style={{ color: theme.colors.textSub }}>Fundamentals</p>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            {[
              { label: 'P/E Ratio', key: 'pe_ratio' },
              { label: 'EPS Growth', key: 'eps_growth', suffix: '%' },
              { label: 'Dividend Yield', key: 'dividend_yield', suffix: '%' },
              { label: 'Market Cap', key: 'market_cap' },
              { label: 'Profit Margin', key: 'profit_margin', suffix: '%' },
              { label: 'Debt/Equity', key: 'debt_to_equity' },
            ].map(({ label, key, suffix }) => {
              const val = fundamentals[key]
              if (val === null || val === undefined) return null
              const display = typeof val === 'number'
                ? suffix ? `${val.toFixed(1)}${suffix}` : val >= 1e9 ? `$${(val / 1e9).toFixed(1)}B` : val >= 1e6 ? `$${(val / 1e6).toFixed(0)}M` : val.toFixed(2)
                : String(val)
              return (
                <div key={key}>
                  <p className="text-[10px] uppercase tracking-wide" style={{ color: theme.colors.textHint }}>{label}</p>
                  <p className="text-sm font-semibold" style={{ color: theme.colors.text }}>{display}</p>
                </div>
              )
            }).filter(Boolean)}
          </div>
        </Card>
      )}

      {/* Signal History */}
      {signalHistory && signalHistory.length > 1 && (
        <Card>
          <p className="text-[11px] font-semibold uppercase tracking-wide mb-3" style={{ color: theme.colors.textSub }}>Signal History</p>
          <div className="space-y-2">
            {signalHistory.map((sig) => (
              <div key={sig.id} className="flex items-center justify-between py-1.5" style={{ borderBottom: `1px solid ${theme.colors.border}` }}>
                <div className="flex items-center gap-2">
                  {sig.action === 'BUY' ? <TrendingUp size={14} style={{ color: theme.colors.up }} /> : <TrendingDown size={14} style={{ color: theme.colors.down }} />}
                  <span className="text-xs font-medium" style={{ color: theme.colors.text }}>{sig.action}</span>
                  <span className="text-[11px]" style={{ color: theme.colors.textSub }}>Score {sig.score}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs tabular-nums" style={{ color: theme.colors.textSub }}>{formatPrice(sig.price_at_signal)}</span>
                  <span className="text-[10px]" style={{ color: theme.colors.textHint }}>
                    {new Date(sig.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}
