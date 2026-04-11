'use client'

import { useEffect, useMemo, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useTheme } from '@/hooks/useTheme'
import { useAuthStore } from '@/store/authStore'
import { useI18nStore } from '@/store/i18nStore'
import { useAllSignals } from '@/hooks/useSignals'
import { useStats } from '@/hooks/useStats'
import { LeftNav } from '@/components/layout/LeftNav'
import { BottomNav } from '@/components/layout/BottomNav'
import { DEFAULT_TIMEZONE, isMarketOpen } from '@/lib/utils'
import { CircleDot, Droplets, TrendingUp, TrendingDown, Minus } from 'lucide-react'

function MarketIndicator() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const { data: signals } = useAllSignals({ limit: 50 })
  const { data: stats } = useStats()
  const [hovered, setHovered] = useState(false)
  const [time, setTime] = useState<Date | null>(null)

  useEffect(() => {
    setTime(new Date())
    const interval = setInterval(() => setTime(new Date()), 30000)
    return () => clearInterval(interval)
  }, [])

  const open = isMarketOpen()
  const regime = signals?.[0]?.market_regime ?? null
  const fg = stats?.fear_greed ?? null
  const im = stats?.intermarket ?? null
  const vt = stats?.vix_term ?? null
  const yc = stats?.yield_curve ?? null
  const cs = stats?.credit_spread ?? null

  const regimeColor = useMemo(() => {
    if (regime === 'CRISIS') return theme.colors.down
    if (regime === 'VOLATILE') return theme.colors.warning
    return theme.colors.up
  }, [regime, theme])

  const regimeLabel = useMemo(() => {
    if (regime === 'CRISIS') return t.market.crisis
    if (regime === 'VOLATILE') return t.market.volatile
    if (regime === 'TRENDING') return t.market.trending
    if (regime === 'RECOVERY') return (t.market as Record<string, string>)?.recovery ?? 'Recovery'
    return null
  }, [regime, t])

  // Macro environment from the latest signal's macro_data
  const environment = useMemo(() => {
    const md = signals?.[0]?.macro_data
    if (!md || typeof md !== 'object') return null
    return (md as Record<string, string>).environment ?? null
  }, [signals])

  const envColor = useMemo(() => {
    if (environment === 'hostile') return theme.colors.down
    if (environment === 'neutral') return theme.colors.warning
    return theme.colors.up
  }, [environment, theme])

  const envLabel = useMemo(() => {
    const m = t.market as Record<string, string>
    if (environment === 'hostile') return m?.hostile ?? 'Hostile'
    if (environment === 'neutral') return m?.envNeutral ?? 'Neutral'
    if (environment === 'favorable') return m?.favorable ?? 'Favorable'
    return null
  }, [environment, t])

  const fgColor = useMemo(() => {
    if (!fg) return theme.colors.textSub
    if (fg.score <= 25) return theme.colors.down
    if (fg.score <= 45) return theme.colors.warning
    if (fg.score >= 55) return theme.colors.up
    return theme.colors.textSub
  }, [fg, theme])

  return (
    <div
      className="fixed top-4 right-6 z-50 flex items-center gap-2 px-3 py-1.5 rounded-full transition-all cursor-default"
      style={{
        backgroundColor: theme.colors.surface,
        border: `1px solid ${theme.colors.border}`,
        boxShadow: theme.isDark ? '0 2px 8px rgba(0,0,0,0.3)' : '0 2px 8px rgba(0,0,0,0.06)',
      }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocus={() => setHovered(true)}
      onBlur={() => setHovered(false)}
      tabIndex={0}
      role="button"
      aria-expanded={hovered}
      aria-label="Market status"
      onKeyDown={(e) => { if (e.key === 'Escape') setHovered(false) }}
    >
      <span
        className="w-1.5 h-1.5 rounded-full shrink-0"
        style={{
          backgroundColor: open ? theme.colors.up : theme.colors.textHint,
          boxShadow: open ? `0 0 6px ${theme.colors.up}80` : 'none',
        }}
      />
      <span className="text-[11px] font-medium" style={{ color: theme.colors.text }}>
        {open ? t.market.open : t.market.closed}
      </span>
      {regimeLabel && (
        <span
          className="text-[9px] font-bold px-1.5 py-0.5 rounded-full"
          style={{ backgroundColor: regimeColor + '18', color: regimeColor }}
        >
          {regimeLabel}
        </span>
      )}
      {envLabel && (
        <span
          className="text-[9px] font-bold px-1.5 py-0.5 rounded-full"
          style={{ backgroundColor: envColor + '18', color: envColor }}
        >
          {envLabel}
        </span>
      )}
      {time && (
        <span className="text-[10px] tabular-nums" style={{ color: theme.colors.textSub }}>
          {time.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: DEFAULT_TIMEZONE })}
        </span>
      )}

      {hovered && (
        <div
          className="absolute top-full right-0 mt-2 rounded-xl p-3 min-w-[220px]"
          style={{
            backgroundColor: theme.colors.surface,
            border: `1px solid ${theme.colors.border}`,
            boxShadow: theme.isDark ? '0 8px 24px rgba(0,0,0,0.4)' : '0 8px 24px rgba(0,0,0,0.1)',
          }}
        >
          <div className="space-y-2">
            {fg && (
              <div className="flex items-center justify-between">
                <span className="text-[10px] uppercase tracking-wide" style={{ color: theme.colors.textHint }}>
                  {t.stats.fearGreed}
                </span>
                <span className="text-[11px] font-bold tabular-nums" style={{ color: fgColor }}>
                  {fg.score.toFixed(0)} <span className="font-normal lowercase" style={{ color: theme.colors.textSub }}>{fg.label}</span>
                </span>
              </div>
            )}

            {/* Intermarket */}
            {im && (im.gold_price != null || im.oil_price != null) && (
              <div className="pt-1.5" style={{ borderTop: `1px solid ${theme.colors.border}` }}>
                <span className="text-[9px] uppercase tracking-wide" style={{ color: theme.colors.textHint }}>Intermarket</span>
                <div className="mt-1 space-y-1">
                  {im.gold_price != null && (
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-1.5">
                        <CircleDot size={10} style={{ color: '#F59E0B' }} />
                        <span className="text-[10px]" style={{ color: theme.colors.text }}>Gold</span>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <span className="text-[10px] font-semibold tabular-nums" style={{ color: theme.colors.text }}>
                          ${im.gold_price.toLocaleString('en-US', { maximumFractionDigits: 0 })}
                        </span>
                        {im.gold_change_pct != null && (
                          <span className="text-[9px] font-medium tabular-nums" style={{ color: im.gold_change_pct >= 0 ? theme.colors.up : theme.colors.down }}>
                            {im.gold_change_pct >= 0 ? '+' : ''}{im.gold_change_pct.toFixed(1)}%
                          </span>
                        )}
                      </div>
                    </div>
                  )}
                  {im.oil_price != null && (
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-1.5">
                        <Droplets size={10} style={{ color: '#3B82F6' }} />
                        <span className="text-[10px]" style={{ color: theme.colors.text }}>Oil</span>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <span className="text-[10px] font-semibold tabular-nums" style={{ color: theme.colors.text }}>
                          ${im.oil_price.toFixed(1)}
                        </span>
                        {im.oil_change_pct != null && (
                          <span className="text-[9px] font-medium tabular-nums" style={{ color: im.oil_change_pct >= 0 ? theme.colors.up : theme.colors.down }}>
                            {im.oil_change_pct >= 0 ? '+' : ''}{im.oil_change_pct.toFixed(1)}%
                          </span>
                        )}
                      </div>
                    </div>
                  )}
                  {im.copper_gold_ratio != null && (
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-1.5">
                        <Minus size={10} style={{ color: theme.colors.textHint }} />
                        <span className="text-[10px]" style={{ color: theme.colors.text }}>Cu/Au</span>
                      </div>
                      <span className="text-[10px] font-semibold tabular-nums" style={{ color: theme.colors.text }}>
                        {im.copper_gold_ratio.toFixed(2)}
                      </span>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Macro indicators */}
            {(yc != null || cs != null || vt) && (
              <div className="pt-1.5" style={{ borderTop: `1px solid ${theme.colors.border}` }}>
                <span className="text-[9px] uppercase tracking-wide" style={{ color: theme.colors.textHint }}>Macro</span>
                <div className="mt-1 space-y-1">
                  {yc != null && (
                    <div className="flex items-center justify-between">
                      <span className="text-[10px]" style={{ color: theme.colors.text }}>Yield Curve</span>
                      <span className="text-[10px] font-semibold tabular-nums" style={{ color: yc < 0 ? theme.colors.down : theme.colors.up }}>
                        {yc > 0 ? '+' : ''}{yc.toFixed(2)}%
                        {yc < 0 && <span className="text-[8px] font-normal ml-1" style={{ color: theme.colors.down }}>INV</span>}
                        {yc > 1.5 && <span className="text-[8px] font-normal ml-1" style={{ color: theme.colors.up }}>STEEP</span>}
                      </span>
                    </div>
                  )}
                  {cs != null && (
                    <div className="flex items-center justify-between">
                      <span className="text-[10px]" style={{ color: theme.colors.text }}>Credit Spread</span>
                      <span className="text-[10px] font-semibold tabular-nums" style={{ color: cs > 3.0 ? theme.colors.down : cs > 2.0 ? theme.colors.warning : theme.colors.textSub }}>
                        {cs.toFixed(2)}%
                        {cs > 5.0 && <span className="text-[8px] font-normal ml-1" style={{ color: theme.colors.down }}>CRISIS</span>}
                        {cs > 3.0 && cs <= 5.0 && <span className="text-[8px] font-normal ml-1" style={{ color: theme.colors.down }}>STRESS</span>}
                        {cs > 2.0 && cs <= 3.0 && <span className="text-[8px] font-normal ml-1" style={{ color: theme.colors.warning }}>ELEV</span>}
                      </span>
                    </div>
                  )}
                  {vt && vt.ratio != null && (
                    <div className="flex items-center justify-between">
                      <span className="text-[10px]" style={{ color: theme.colors.text }}>VIX Term</span>
                      <div className="flex items-center gap-1">
                        {vt.ratio > 1.0
                          ? <TrendingUp size={9} style={{ color: theme.colors.down }} />
                          : <TrendingDown size={9} style={{ color: theme.colors.up }} />
                        }
                        <span className="text-[10px] font-semibold tabular-nums" style={{ color: vt.ratio > 1.1 ? theme.colors.down : theme.colors.textSub }}>
                          {vt.ratio.toFixed(3)}
                        </span>
                        <span className="text-[8px]" style={{ color: theme.colors.textHint }}>
                          {vt.structure === 'backwardation' ? 'BWD' : 'CTG'}
                        </span>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Next scan & AI cost */}
            <div className="pt-1.5 space-y-1.5" style={{ borderTop: `1px solid ${theme.colors.border}` }}>
              <div className="flex items-center justify-between">
                <span className="text-[10px] uppercase tracking-wide" style={{ color: theme.colors.textHint }}>
                  {t.nav.nextScan}
                </span>
                <span className="text-[11px] tabular-nums" style={{ color: theme.colors.textSub }}>
                  {!open
                    ? (t.scans?.resumesMonday ?? 'Resumes Monday')
                    : stats?.next_scan_time
                      ? new Date(stats.next_scan_time).toLocaleTimeString('en-US', {
                          hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York', timeZoneName: 'short',
                        })
                      : '--'
                  }
                </span>
              </div>
              {stats && (
                <div className="flex items-center justify-between">
                  <span className="text-[10px] uppercase tracking-wide" style={{ color: theme.colors.textHint }}>
                    {t.stats.aiCost}
                  </span>
                  <span className="text-[11px] font-semibold tabular-nums" style={{ color: theme.colors.warning }}>
                    ${stats.ai_cost_today.toFixed(2)}
                  </span>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const token = useAuthStore((s) => s.token)
  const setToken = useAuthStore((s) => s.setToken)
  const [lastLogin, setLastLogin] = useState<string | null>(null)

  useEffect(() => {
    const saved = localStorage.getItem('signa-last-login')
    if (saved) setLastLogin(saved)
  }, [])
  useEffect(() => {
    const saved = localStorage.getItem('signa-token')
    if (saved && !isAuthenticated) {
      setToken(saved)
    } else if (!saved && !isAuthenticated) {
      router.push('/login')
    }
  }, [isAuthenticated, setToken, router])

  if (!isAuthenticated && !token && typeof window !== 'undefined' && !localStorage.getItem('signa-token')) {
    return null
  }

  return (
    <>
      <LeftNav />
      <div className="hidden md:block">
        <MarketIndicator />
      </div>
      {/* Desktop: offset for floating nav */}
      <div className="hidden md:block md:ml-[72px]">
        <main className="max-w-[1200px] mx-auto px-6 lg:px-8 py-6">
          <div className="min-w-0">{children}</div>
        </main>
      </div>
      {/* Mobile: full width */}
      <div className="md:hidden">
        <main className="px-4 py-6 pb-24">
          {children}
        </main>
      </div>
      <BottomNav />
      {/* Last login — fixed bottom right */}
      {lastLogin && (
        <div className="hidden md:block fixed bottom-4 right-6 z-40">
          <span className="text-[10px]" style={{ color: theme.colors.textHint }}>
            {t.overview.lastLogin} {new Date(lastLogin).toLocaleString('en-US', {
              month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
              timeZone: 'America/New_York', timeZoneName: 'short',
            })}
          </span>
        </div>
      )}
    </>
  )
}
