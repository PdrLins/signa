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

  const regimeColor = useMemo(() => {
    if (regime === 'CRISIS') return theme.colors.down
    if (regime === 'VOLATILE') return theme.colors.warning
    return theme.colors.up
  }, [regime, theme])

  const regimeLabel = useMemo(() => {
    if (regime === 'CRISIS') return t.market.crisis
    if (regime === 'VOLATILE') return t.market.volatile
    if (regime === 'TRENDING') return t.market.trending
    return null
  }, [regime, t])

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
          <div className="space-y-2.5">
            {fg && (
              <div className="flex items-center justify-between">
                <span className="text-[10px] uppercase tracking-wide" style={{ color: theme.colors.textHint }}>
                  {t.stats.fearGreed}
                </span>
                <span className="text-[11px] font-bold tabular-nums" style={{ color: fgColor }}>
                  {fg.score.toFixed(0)} -- {fg.label}
                </span>
              </div>
            )}
            {stats?.next_scan_time && (
              <div className="flex items-center justify-between">
                <span className="text-[10px] uppercase tracking-wide" style={{ color: theme.colors.textHint }}>
                  {t.nav.nextScan}
                </span>
                <span className="text-[11px] tabular-nums" style={{ color: theme.colors.textSub }}>
                  {new Date(stats.next_scan_time).toLocaleTimeString('en-US', {
                    hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York', timeZoneName: 'short',
                  })}
                </span>
              </div>
            )}
            {stats && (
              <div className="flex items-center justify-between pt-1.5" style={{ borderTop: `1px solid ${theme.colors.border}` }}>
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
