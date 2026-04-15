'use client'

import { useState, useEffect, useMemo } from 'react'
import { usePathname } from 'next/navigation'
import Link from 'next/link'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useAuthStore } from '@/store/authStore'
import { useAllSignals } from '@/hooks/useSignals'
import { useStats } from '@/hooks/useStats'
import { isMarketOpen, DEFAULT_TIMEZONE } from '@/lib/utils'
import {
  LayoutDashboard,
  TrendingUp,
  Star,
  HelpCircle,
  Settings,
  Brain,
  ScrollText,
  Plug,
  Activity,
  LogOut,
} from 'lucide-react'

export function LeftNav() {
  const theme = useTheme()
  const pathname = usePathname()
  const t = useI18nStore((s) => s.t)
  const logout = useAuthStore((s) => s.logout)

  // Market status data (mirrors the old MarketIndicator)
  const open = isMarketOpen()
  const { data: signals } = useAllSignals({ limit: 50 })
  const { data: stats } = useStats()
  const [marketHovered, setMarketHovered] = useState(false)
  const [time, setTime] = useState<Date | null>(null)

  useEffect(() => {
    setTime(new Date())
    const interval = setInterval(() => setTime(new Date()), 30000)
    return () => clearInterval(interval)
  }, [])

  const regime = signals?.[0]?.market_regime ?? null
  const fg = stats?.fear_greed ?? null
  const md = signals?.[0]?.macro_data as Record<string, unknown> | null
  const environment = md?.environment as string | null
  const statsAny = stats as unknown as Record<string, unknown> | undefined
  const im = statsAny?.intermarket as Record<string, number> | null
  const vt = statsAny?.vix_term as Record<string, number | string> | null
  const yc = statsAny?.yield_curve as number | null
  const cs = statsAny?.credit_spread as number | null

  const regimeColor = useMemo(() => {
    if (regime === 'CRISIS') return theme.colors.down
    if (regime === 'VOLATILE') return theme.colors.warning
    return theme.colors.up
  }, [regime, theme])

  const dotColor = open ? theme.colors.up : theme.colors.textHint

  const NAV_ITEMS = [
    { label: t.nav.overview, href: '/overview', icon: LayoutDashboard },
    { label: t.nav.signals, href: '/signals', icon: TrendingUp },
    { label: t.nav.watchlist, href: '/watchlist', icon: Star },
    // TODO: Uncomment when portfolio manual tracking is implemented
    // { label: t.nav.portfolio, href: '/portfolio', icon: Briefcase },
    { label: t.nav.brain, href: '/brain', icon: Brain },
    { label: t.nav.brainPerformance, href: '/brain/performance', icon: Activity },
    { label: t.nav.logs, href: '/logs', icon: ScrollText },
    { label: t.nav.integrations, href: '/integrations', icon: Plug },
    { label: t.nav.howItWorks, href: '/how-it-works', icon: HelpCircle },
    { label: t.nav.settings, href: '/settings', icon: Settings },
  ]

  return (
    <nav
      className="hidden md:flex flex-col items-center fixed left-5 top-1/2 -translate-y-1/2 z-50 py-3 px-1.5 gap-1 rounded-2xl"
      style={{
        backgroundColor: theme.colors.surface,
        border: `1px solid ${theme.colors.border}`,
        boxShadow: theme.isDark
          ? '0 4px 24px rgba(0,0,0,0.4)'
          : '0 4px 24px rgba(0,0,0,0.08)',
      }}
    >
      {/* Market status dot — hover for full macro panel */}
      <div
        className="relative flex items-center justify-center w-10 h-10 rounded-xl transition-all cursor-default"
        onMouseEnter={() => setMarketHovered(true)}
        onMouseLeave={() => setMarketHovered(false)}
      >
        <span
          className="w-3 h-3 rounded-full"
          style={{
            backgroundColor: dotColor,
            boxShadow: open ? `0 0 8px ${theme.colors.up}60` : 'none',
          }}
        />
        {marketHovered && (
          <div
            className="absolute left-full ml-3 top-0 rounded-xl p-3 min-w-[240px] z-[60]"
            style={{
              backgroundColor: theme.colors.surface,
              border: `1px solid ${theme.colors.border}`,
              boxShadow: theme.isDark ? '0 8px 24px rgba(0,0,0,0.4)' : '0 8px 24px rgba(0,0,0,0.1)',
            }}
          >
            <div className="space-y-2">
              {/* Status + time */}
              <div className="flex items-center justify-between">
                <span className="text-[12px] font-medium" style={{ color: theme.colors.text }}>
                  {open ? (t.market?.open ?? 'Market Open') : (t.market?.closed ?? 'Market Closed')}
                </span>
                {time && (
                  <span className="text-[12px] tabular-nums" style={{ color: theme.colors.textSub }}>
                    {time.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: DEFAULT_TIMEZONE })}
                  </span>
                )}
              </div>
              {/* Regime + environment badges */}
              <div className="flex items-center gap-2">
                {regime && (
                  <span className="text-[12px] font-bold px-1.5 py-0.5 rounded-full" style={{ backgroundColor: regimeColor + '18', color: regimeColor }}>
                    {regime}
                  </span>
                )}
                {environment && (
                  <span className="text-[12px] font-bold px-1.5 py-0.5 rounded-full" style={{
                    backgroundColor: (environment === 'hostile' ? theme.colors.down : environment === 'neutral' ? theme.colors.warning : theme.colors.up) + '18',
                    color: environment === 'hostile' ? theme.colors.down : environment === 'neutral' ? theme.colors.warning : theme.colors.up,
                  }}>
                    {environment}
                  </span>
                )}
              </div>
              {/* Fear & Greed */}
              {fg && (
                <div className="flex items-center justify-between pt-1.5" style={{ borderTop: `1px solid ${theme.colors.border}` }}>
                  <span className="text-[12px]" style={{ color: theme.colors.textHint }}>Fear & Greed</span>
                  <span className="text-[12px] font-bold tabular-nums" style={{
                    color: fg.score <= 25 ? theme.colors.down : fg.score <= 45 ? theme.colors.warning : fg.score >= 55 ? theme.colors.up : theme.colors.textSub,
                  }}>
                    {fg.score.toFixed(0)} <span className="font-normal lowercase" style={{ color: theme.colors.textSub }}>{fg.label}</span>
                  </span>
                </div>
              )}
              {/* Intermarket */}
              {im && (im.gold_price != null || im.oil_price != null) && (
                <div className="pt-1.5" style={{ borderTop: `1px solid ${theme.colors.border}` }}>
                  <span className="text-[12px] uppercase tracking-wide" style={{ color: theme.colors.textHint }}>Intermarket</span>
                  <div className="mt-1 space-y-1">
                    {im.gold_price != null && (
                      <div className="flex items-center justify-between">
                        <span className="text-[12px]" style={{ color: theme.colors.text }}>Gold</span>
                        <div className="flex items-center gap-1.5">
                          <span className="text-[12px] font-semibold tabular-nums" style={{ color: theme.colors.text }}>
                            ${im.gold_price.toLocaleString('en-US', { maximumFractionDigits: 0 })}
                          </span>
                          {im.gold_change_pct != null && (
                            <span className="text-[12px] font-medium tabular-nums" style={{ color: im.gold_change_pct >= 0 ? theme.colors.up : theme.colors.down }}>
                              {im.gold_change_pct >= 0 ? '+' : ''}{im.gold_change_pct.toFixed(1)}%
                            </span>
                          )}
                        </div>
                      </div>
                    )}
                    {im.oil_price != null && (
                      <div className="flex items-center justify-between">
                        <span className="text-[12px]" style={{ color: theme.colors.text }}>Oil</span>
                        <div className="flex items-center gap-1.5">
                          <span className="text-[12px] font-semibold tabular-nums" style={{ color: theme.colors.text }}>
                            ${im.oil_price.toFixed(1)}
                          </span>
                          {im.oil_change_pct != null && (
                            <span className="text-[12px] font-medium tabular-nums" style={{ color: im.oil_change_pct >= 0 ? theme.colors.up : theme.colors.down }}>
                              {im.oil_change_pct >= 0 ? '+' : ''}{im.oil_change_pct.toFixed(1)}%
                            </span>
                          )}
                        </div>
                      </div>
                    )}
                    {im.copper_gold_ratio != null && (
                      <div className="flex items-center justify-between">
                        <span className="text-[12px]" style={{ color: theme.colors.text }}>Cu/Au</span>
                        <span className="text-[12px] font-semibold tabular-nums" style={{ color: theme.colors.text }}>
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
                  <span className="text-[12px] uppercase tracking-wide" style={{ color: theme.colors.textHint }}>Macro</span>
                  <div className="mt-1 space-y-1">
                    {yc != null && (
                      <div className="flex items-center justify-between">
                        <span className="text-[12px]" style={{ color: theme.colors.text }}>Yield Curve</span>
                        <span className="text-[12px] font-semibold tabular-nums" style={{ color: yc < 0 ? theme.colors.down : theme.colors.up }}>
                          {yc > 0 ? '+' : ''}{yc.toFixed(2)}%
                          {yc < 0 && <span className="text-[9px] font-normal ml-1" style={{ color: theme.colors.down }}>INV</span>}
                        </span>
                      </div>
                    )}
                    {cs != null && (
                      <div className="flex items-center justify-between">
                        <span className="text-[12px]" style={{ color: theme.colors.text }}>Credit Spread</span>
                        <span className="text-[12px] font-semibold tabular-nums" style={{ color: cs > 3.0 ? theme.colors.down : cs > 2.0 ? theme.colors.warning : theme.colors.textSub }}>
                          {cs.toFixed(2)}%
                        </span>
                      </div>
                    )}
                    {vt && vt.ratio != null && (
                      <div className="flex items-center justify-between">
                        <span className="text-[12px]" style={{ color: theme.colors.text }}>VIX Term</span>
                        <span className="text-[12px] font-semibold tabular-nums" style={{ color: (vt.ratio as number) > 1.1 ? theme.colors.down : theme.colors.textSub }}>
                          {(vt.ratio as number).toFixed(3)} {vt.structure === 'backwardation' ? 'BWD' : 'CTG'}
                        </span>
                      </div>
                    )}
                  </div>
                </div>
              )}
              {/* Next scan & AI cost */}
              <div className="pt-1.5 space-y-1.5" style={{ borderTop: `1px solid ${theme.colors.border}` }}>
                <div className="flex items-center justify-between">
                  <span className="text-[12px]" style={{ color: theme.colors.textHint }}>{t.nav?.nextScan ?? 'Next scan'}</span>
                  <span className="text-[12px] tabular-nums" style={{ color: theme.colors.textSub }}>
                    {stats?.next_scan_time
                      ? new Date(stats.next_scan_time).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: DEFAULT_TIMEZONE, timeZoneName: 'short' })
                      : '--'}
                  </span>
                </div>
                {stats && (
                  <div className="flex items-center justify-between">
                    <span className="text-[12px]" style={{ color: theme.colors.textHint }}>AI Cost</span>
                    <span className="text-[12px] font-semibold tabular-nums" style={{ color: theme.colors.warning }}>
                      ${stats.ai_cost_today.toFixed(2)}
                    </span>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="w-6 h-px mx-auto mb-1" style={{ backgroundColor: theme.colors.border }} />

      {NAV_ITEMS.map((item, i) => {
        const isActive = pathname === item.href || (item.href === '/signals' && pathname.startsWith('/signals/'))
        const isLast = i === NAV_ITEMS.length - 1
        return (
          <div key={item.href}>
            {/* Separator before settings */}
            {isLast && (
              <div
                className="w-6 h-px mx-auto mb-1"
                style={{ backgroundColor: theme.colors.border }}
              />
            )}
            <Link
              href={item.href}
              className="flex items-center justify-center w-10 h-10 rounded-xl transition-all"
              style={{
                backgroundColor: isActive ? theme.colors.primary + '15' : 'transparent',
                color: isActive ? theme.colors.primary : theme.colors.textSub,
              }}
              title={item.label}
            >
              <item.icon size={20} strokeWidth={isActive ? 2.2 : 1.8} />
            </Link>
          </div>
        )
      })}

      {/* Logout */}
      <div
        className="w-6 h-px mx-auto my-1"
        style={{ backgroundColor: theme.colors.border }}
      />
      <button
        onClick={() => {
          logout()
          window.location.href = '/login'
        }}
        className="flex items-center justify-center w-10 h-10 rounded-xl transition-all hover:opacity-80"
        style={{ color: theme.colors.down }}
        title={t.settings.logOut}
      >
        <LogOut size={18} strokeWidth={1.8} />
      </button>
    </nav>
  )
}
