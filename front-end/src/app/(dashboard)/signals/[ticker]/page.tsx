'use client'

import { useMemo } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useToast } from '@/hooks/useToast'
import { useWatchlist, useAddTicker, useRemoveTicker } from '@/hooks/useWatchlist'
import { tickersApi, signalsApi, client } from '@/lib/api'
import { Card } from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { ScoreRing } from '@/components/ui/ScoreRing'
import { ProgressBar } from '@/components/ui/ProgressBar'
import { Skeleton } from '@/components/ui/Skeleton'
import { PriceChart } from '@/components/charts/PriceChart'
import { Sidebar } from '@/components/layout/Sidebar'
import { formatPrice } from '@/lib/utils'
import { ArrowLeft, Star, TrendingUp, TrendingDown, Brain, BookOpen } from 'lucide-react'

export default function TickerDetailPage() {
  const params = useParams()
  const ticker = (params.ticker as string)?.toUpperCase() ?? ''
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const toast = useToast()
  const { data: watchlist } = useWatchlist()
  const addTicker = useAddTicker()
  const removeTicker = useRemoveTicker()
  const isWatchlisted = watchlist?.some((w) => w.symbol === ticker) ?? false

  const { data: detail, isLoading: loadingDetail } = useQuery({
    queryKey: ['ticker', ticker],
    queryFn: () => tickersApi.getDetail(ticker),
    enabled: !!ticker,
  })

  const { data: signalHistory, isError: signalHistoryError } = useQuery({
    queryKey: ['signals', ticker, 'history'],
    queryFn: async () => {
      const res = await signalsApi.getByTicker(ticker, 10)
      return res.signals
    },
    enabled: !!ticker,
  })

  const { data: brainInsights, isError: brainInsightsError } = useQuery({
    queryKey: ['brain', 'insights', ticker],
    queryFn: async () => {
      const res = await client.get(`/brain/insights/${ticker}`)
      return res.data as {
        summary: string
        key_points: Array<{ type: string; text: string }>
        knowledge: Array<{ concept: string; explanation: string }>
      }
    },
    enabled: !!ticker,
    staleTime: 60_000,
  })

  const latest = signalHistory?.[0]
  const fundamentals = detail?.fundamentals as Record<string, string | number | null> | undefined
  const currentPrice = detail?.current_price as number | undefined

  // Scoring weights
  const isHighRisk = latest?.bucket === 'HIGH_RISK'
  const weights = useMemo(() => isHighRisk
    ? [
        { label: t.signal.sentimentXTwitter, pct: 35, color: theme.colors.primary },
        { label: t.signal.catalyst, pct: 30, color: theme.colors.up },
        { label: t.signal.technicalMomentum, pct: 25, color: theme.colors.warning },
        { label: t.signal.fundamentals, pct: 10, color: theme.colors.textSub },
      ]
    : [
        { label: t.signal.dividendReliability, pct: 35, color: theme.colors.up },
        { label: t.signal.fundamentalHealth, pct: 30, color: theme.colors.primary },
        { label: t.signal.macroConditions, pct: 25, color: theme.colors.warning },
        { label: t.signal.sentiment, pct: 10, color: theme.colors.textSub },
      ], [isHighRisk, t, theme])

  if (loadingDetail) {
    return (
      <div className="space-y-4">
        <Skeleton width={200} height={28} />
        <Skeleton width="100%" height={200} borderRadius={14} />
        <Skeleton width="100%" height={150} borderRadius={14} />
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Back + Header */}
      <div className="flex items-center gap-3">
        <Link href="/signals" aria-label="Go back" className="p-1.5 rounded-lg transition-opacity hover:opacity-70" style={{ color: theme.colors.textSub }}>
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
            {latest?.is_discovered && (
              <span className="text-[10px] font-bold px-2 py-0.5 rounded-md" style={{ backgroundColor: theme.colors.primary + '18', color: theme.colors.primary }}>
                Discovered
              </span>
            )}
            <button
              onClick={() => {
                if (isWatchlisted) {
                  removeTicker.mutate(ticker, {
                    onSuccess: () => toast.show(`${ticker} ${t.signal.removedFromWatchlist}`, 'info'),
                    onError: (err) => toast.show(err?.message || t.signal.failed, 'error'),
                  })
                } else {
                  addTicker.mutate(ticker, {
                    onSuccess: () => toast.show(`${ticker} ${t.signal.addedToWatchlist}`, 'success'),
                    onError: (err) => toast.show(err?.message || t.signal.failed, 'error'),
                  })
                }
              }}
              disabled={addTicker.isPending || removeTicker.isPending}
              className="p-1 rounded transition-opacity hover:opacity-70"
              title={isWatchlisted ? t.signal.removeFromWatchlist : t.signal.addToWatchlist}
              aria-label="Toggle watchlist"
            >
              <Star
                size={18}
                fill={isWatchlisted ? theme.colors.warning : 'none'}
                style={{ color: isWatchlisted ? theme.colors.warning : theme.colors.textHint }}
              />
            </button>
          </div>
          {detail?.company_name && (
            <p className="text-[13px]" style={{ color: theme.colors.text }}>{detail.company_name as string}</p>
          )}
          <p className="text-[11px]" style={{ color: theme.colors.textSub }}>
            {detail?.exchange as string ?? ''} &middot; {(detail?.asset_type as string) === 'CRYPTO' ? t.signal.crypto : t.signal.equity}
          </p>
        </div>
        <div className="text-right">
          {(() => {
            const fund = fundamentals as Record<string, unknown> | undefined
            const regPrice = fund?.regular_market_price as number | undefined
            const regChange = fund?.regular_market_change as number | undefined
            const regChangePct = fund?.regular_market_change_pct as number | undefined
            const postPrice = fund?.post_market_price as number | undefined
            const postChange = fund?.post_market_change as number | undefined
            const postChangePct = fund?.post_market_change_pct as number | undefined
            const prePrice = fund?.pre_market_price as number | undefined
            const preChange = fund?.pre_market_change as number | undefined
            const preChangePct = fund?.pre_market_change_pct as number | undefined

            const displayPrice = regPrice ?? currentPrice
            const isUp = (regChange ?? 0) >= 0

            return (
              <>
                <p className="text-2xl font-bold tabular-nums" style={{ color: theme.colors.text }}>
                  {formatPrice(displayPrice ?? null)}
                </p>
                {regChange != null && regChangePct != null && (
                  <p className="text-[12px] font-semibold tabular-nums" style={{ color: isUp ? theme.colors.up : theme.colors.down }}>
                    {regChange >= 0 ? '+' : ''}{regChange.toFixed(2)} ({regChange >= 0 ? '+' : ''}{regChangePct.toFixed(2)}%)
                  </p>
                )}
                {postPrice != null && postChange != null && postChangePct != null && (
                  <div className="mt-1 pt-1" style={{ borderTop: `1px solid ${theme.colors.border}20` }}>
                    <p className="text-[10px]" style={{ color: theme.colors.textHint }}>{t.signal.afterHours}</p>
                    <p className="text-[12px] font-semibold tabular-nums" style={{ color: postChange >= 0 ? theme.colors.up : theme.colors.down }}>
                      {formatPrice(postPrice)} ({postChange >= 0 ? '+' : ''}{postChangePct.toFixed(2)}%)
                    </p>
                  </div>
                )}
                {prePrice != null && preChange != null && preChangePct != null && !postPrice && (
                  <div className="mt-1 pt-1" style={{ borderTop: `1px solid ${theme.colors.border}20` }}>
                    <p className="text-[10px]" style={{ color: theme.colors.textHint }}>{t.signal.preMarket}</p>
                    <p className="text-[12px] font-semibold tabular-nums" style={{ color: preChange >= 0 ? theme.colors.up : theme.colors.down }}>
                      {formatPrice(prePrice)} ({preChange >= 0 ? '+' : ''}{preChangePct.toFixed(2)}%)
                    </p>
                  </div>
                )}
              </>
            )
          })()}
        </div>
      </div>

      {/* Period changes + benchmark */}
      {(() => {
        const pc = detail?.period_changes as Record<string, unknown> | undefined
        const periods = [
          { label: '1W', key: 'week_change_pct' },
          { label: '1M', key: 'month_change_pct' },
          { label: '3M', key: 'three_month_change_pct' },
          { label: 'YTD', key: 'ytd_change_pct' },
        ]
        const spy = pc?.spy as Record<string, unknown> | undefined
        const hasAny = periods.some(p => pc?.[p.key] != null)
        if (!hasAny) return null
        return (
          <div className="flex flex-wrap items-center gap-2">
            {periods.map(({ label, key }) => {
              const val = pc?.[key] as number | undefined
              const spyVal = spy?.[key] as number | undefined
              if (val == null) return null
              const isUp = val >= 0
              return (
                <div key={key} className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg" style={{ backgroundColor: theme.colors.surfaceAlt }}>
                  <span className="text-[10px] font-medium" style={{ color: theme.colors.textHint }}>{label}</span>
                  <span className="text-[11px] font-bold tabular-nums" style={{ color: isUp ? theme.colors.up : theme.colors.down }}>
                    {isUp ? '+' : ''}{val.toFixed(1)}%
                  </span>
                  {spyVal != null && (
                    <span className="text-[9px] tabular-nums" style={{ color: theme.colors.textHint }}>
                      vs {spyVal >= 0 ? '+' : ''}{spyVal.toFixed(1)}%
                    </span>
                  )}
                </div>
              )
            })}
          </div>
        )
      })()}

      {/* Content + Sidebar grid */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_300px] gap-6 items-start">
        <div className="space-y-4">

      {/* Price Chart */}
      <Card>
        <PriceChart symbol={ticker} />
      </Card>

      {/* Latest Signal */}
      {latest && (
        <Card>
          <div className="flex items-center justify-between mb-3">
            <p className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: theme.colors.textSub }}>{t.signal.latestSignal}</p>
            <div className="flex items-center gap-1.5 flex-wrap">
              <Badge variant={latest.action === 'BUY' ? 'buy' : latest.action === 'SELL' ? 'sell' : latest.action === 'AVOID' ? 'avoid' : 'hold'}>
                {latest.action}
              </Badge>
              {latest.signal_style === 'CONTRARIAN' && <Badge variant="upgraded">CONTRARIAN</Badge>}
              {latest.signal_style === 'MOMENTUM' && <Badge variant="confirmed">MOMENTUM</Badge>}
              <Badge variant={latest.status === 'CONFIRMED' ? 'confirmed' : latest.status === 'WEAKENING' ? 'weakening' : latest.status === 'UPGRADED' ? 'upgraded' : 'cancelled'}>
                {latest.status}
              </Badge>
              {latest.account_recommendation && (
                <Badge variant={latest.account_recommendation === 'TFSA' ? 'safe' : 'risk'}>
                  {latest.account_recommendation}
                </Badge>
              )}
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

          {/* Confidence + Regime */}
          {(latest.confidence > 0 || latest.market_regime) && (
            <div className="flex items-center gap-4 mb-4">
              {latest.confidence > 0 && (
                <div>
                  <p className="text-[10px] uppercase tracking-wide" style={{ color: theme.colors.textHint }}>{t.signal.confidence}</p>
                  <p className="text-sm font-semibold" style={{ color: theme.colors.primary }}>{latest.confidence}%</p>
                </div>
              )}
              {latest.market_regime && (
                <div>
                  <p className="text-[10px] uppercase tracking-wide" style={{ color: theme.colors.textHint }}>Regime</p>
                  <Badge variant={latest.market_regime === 'TRENDING' ? 'confirmed' : latest.market_regime === 'VOLATILE' ? 'hold' : 'cancelled'}>
                    {latest.market_regime}
                  </Badge>
                </div>
              )}
            </div>
          )}

          {/* Reasoning */}
          {latest.reasoning && (
            <div className="mb-3">
              <p className="text-[10px] uppercase tracking-wide mb-1" style={{ color: theme.colors.textHint }}>{t.signal.whyThisSignal}</p>
              <p className="text-sm leading-relaxed" style={{ color: theme.colors.textSub }}>{latest.reasoning}</p>
            </div>
          )}

          {/* Score breakdown */}
          <div>
            <p className="text-[10px] uppercase tracking-wide mb-2" style={{ color: theme.colors.textHint }}>
              {t.signal.scoreBreakdown} ({isHighRisk ? t.signal.highRiskModel : t.signal.safeIncomeModel})
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
          <p className="text-[11px] font-semibold uppercase tracking-wide mb-3" style={{ color: theme.colors.textSub }}>{t.signal.fundamentals}</p>

          {/* Company description */}
          {fundamentals.description && (
            <p className="text-[11px] leading-relaxed mb-3 line-clamp-3" style={{ color: theme.colors.textSub }}>
              {fundamentals.description as string}
            </p>
          )}

          {/* Sector & Industry */}
          {(fundamentals.sector || fundamentals.industry) && (
            <p className="text-[11px] mb-3" style={{ color: theme.colors.textHint }}>
              {fundamentals.sector as string}{fundamentals.industry ? ` · ${fundamentals.industry as string}` : ''}
            </p>
          )}

          {/* 52-week range */}
          {fundamentals['52w_low'] != null && fundamentals['52w_high'] != null && currentPrice && (
            <div className="mb-4">
              <p className="text-[10px] uppercase tracking-wide mb-1.5" style={{ color: theme.colors.textHint }}>{t.signal.fiftyTwoWeek}</p>
              <div className="flex items-center gap-2">
                <span className="text-[10px] tabular-nums" style={{ color: theme.colors.down }}>${Number(fundamentals['52w_low']).toFixed(0)}</span>
                <div className="flex-1 h-1.5 rounded-full relative" style={{ backgroundColor: theme.colors.surfaceAlt }}>
                  <div
                    className="absolute h-full rounded-full"
                    style={{
                      backgroundColor: theme.colors.primary,
                      left: '0%',
                      width: `${Math.min(100, Math.max(0, ((currentPrice - Number(fundamentals['52w_low'])) / (Number(fundamentals['52w_high']) - Number(fundamentals['52w_low']))) * 100))}%`,
                    }}
                  />
                  <div
                    className="absolute w-2.5 h-2.5 rounded-full -top-0.5"
                    style={{
                      backgroundColor: theme.colors.primary,
                      border: `2px solid ${theme.colors.surface}`,
                      left: `${Math.min(98, Math.max(2, ((currentPrice - Number(fundamentals['52w_low'])) / (Number(fundamentals['52w_high']) - Number(fundamentals['52w_low']))) * 100))}%`,
                      transform: 'translateX(-50%)',
                    }}
                  />
                </div>
                <span className="text-[10px] tabular-nums" style={{ color: theme.colors.up }}>${Number(fundamentals['52w_high']).toFixed(0)}</span>
              </div>
            </div>
          )}

          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            {[
              { label: t.signal.peRatio, key: 'pe_ratio' },
              { label: t.signal.forwardPE, key: 'forward_pe' },
              { label: t.signal.epsGrowth, key: 'eps_growth', suffix: '%' },
              { label: t.signal.dividendYield, key: 'dividend_yield', suffix: '%' },
              { label: t.signal.payoutRatio, key: 'payout_ratio', suffix: '%' },
              { label: t.signal.marketCap, key: 'market_cap' },
              { label: t.signal.profitMargin, key: 'profit_margin', suffix: '%' },
              { label: t.signal.revenueGrowth, key: 'revenue_growth', suffix: '%' },
              { label: t.signal.debtEquity, key: 'debt_to_equity' },
              { label: t.signal.betaLabel, key: 'beta' },
            ].map(({ label, key, suffix }) => {
              const val = fundamentals[key]
              if (val === null || val === undefined) return null
              const display = typeof val === 'number'
                ? suffix ? `${(val * (key === 'payout_ratio' || key === 'profit_margin' || key === 'revenue_growth' ? 100 : 1)).toFixed(1)}${suffix}` : val >= 1e9 ? `$${(val / 1e9).toFixed(1)}B` : val >= 1e6 ? `$${(val / 1e6).toFixed(0)}M` : val.toFixed(2)
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

      {/* Brain Insights Error */}
      {brainInsightsError && (
        <Card>
          <p className="text-xs" style={{ color: theme.colors.down }}>{t.error.failedBrainInsights}</p>
        </Card>
      )}

      {/* Brain Insights */}
      {brainInsights && (
        <Card>
          <div className="flex items-center gap-2 mb-3">
            <Brain size={16} style={{ color: theme.colors.primary }} />
            <p className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: theme.colors.textSub }}>
              {t.signal.brainSays}
            </p>
          </div>

          {/* Summary */}
          <div
            className="rounded-xl px-4 py-3 mb-3"
            style={{ backgroundColor: theme.colors.primary + '08', border: `1px solid ${theme.colors.primary}15` }}
          >
            <p className="text-[13px] leading-relaxed" style={{ color: theme.colors.text }}>
              {brainInsights.summary}
            </p>
          </div>

          {/* Key Points — specific to this ticker */}
          {brainInsights.key_points?.length > 0 && (
            <div className="space-y-2 mb-3">
              {brainInsights.key_points.map((point, i) => {
                const color = point.type === 'positive' ? theme.colors.up
                  : point.type === 'warning' ? theme.colors.down
                  : theme.colors.primary
                const icon = point.type === 'positive' ? '✓'
                  : point.type === 'warning' ? '!'
                  : '→'
                return (
                  <div key={i} className="flex items-start gap-2.5">
                    <span
                      className="w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0"
                      style={{ backgroundColor: color + '15', color }}
                    >
                      {icon}
                    </span>
                    <p className="text-[12px] leading-relaxed pt-0.5" style={{ color: theme.colors.text }}>
                      {point.text}
                    </p>
                  </div>
                )
              })}
            </div>
          )}

          {/* Knowledge */}
          {brainInsights.knowledge?.length > 0 && (
            <div>
              <p className="text-[10px] uppercase tracking-wide mb-2" style={{ color: theme.colors.textHint }}>
                {t.signal.brainKnowledge}
              </p>
              <div className="space-y-1.5">
                {brainInsights.knowledge.map((k) => (
                  <div key={k.concept} className="flex items-start gap-2">
                    <BookOpen size={12} className="shrink-0 mt-0.5" style={{ color: theme.colors.primary }} />
                    <div>
                      <span className="text-[11px] font-semibold" style={{ color: theme.colors.text }}>{k.concept}</span>
                      <p className="text-[10px] leading-relaxed" style={{ color: theme.colors.textSub }}>{k.explanation}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </Card>
      )}

      {/* Signal History Error */}
      {signalHistoryError && (
        <Card>
          <p className="text-xs" style={{ color: theme.colors.down }}>{t.error.failedSignalHistory}</p>
        </Card>
      )}

      {/* Signal History */}
      {signalHistory && signalHistory.length > 1 && (
        <Card>
          <p className="text-[11px] font-semibold uppercase tracking-wide mb-3" style={{ color: theme.colors.textSub }}>{t.signal.signalHistory}</p>
          <div className="space-y-2">
            {signalHistory.map((sig) => (
              <div key={sig.id} className="flex items-center justify-between py-1.5" style={{ borderBottom: `1px solid ${theme.colors.border}` }}>
                <div className="flex items-center gap-2">
                  {sig.action === 'BUY' ? <TrendingUp size={14} style={{ color: theme.colors.up }} /> : <TrendingDown size={14} style={{ color: theme.colors.down }} />}
                  <span className="text-xs font-medium" style={{ color: theme.colors.text }}>{sig.action}</span>
                  <span className="text-[11px]" style={{ color: theme.colors.textSub }}>{t.signal.score} {sig.score}</span>
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
        <div className="sticky top-6 hidden lg:block">
          <Sidebar />
        </div>
      </div>
    </div>
  )
}
