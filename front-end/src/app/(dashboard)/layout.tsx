'use client'

import { useEffect, useState } from 'react'
import { usePathname, useRouter } from 'next/navigation'
import { useAccess } from '@/hooks/useAccess'
import { areaForPath, homePath } from '@/lib/access'
import { LockedArea } from '@/components/access/LockedArea'
import { useTheme } from '@/hooks/useTheme'
import { useAuthStore } from '@/store/authStore'
import { useI18nStore, intlLocale } from '@/store/i18nStore'
import { LeftNav } from '@/components/layout/LeftNav'
import { BottomNav } from '@/components/layout/BottomNav'

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const token = useAuthStore((s) => s.token)
  const setToken = useAuthStore((s) => s.setToken)
  const [lastLogin, setLastLogin] = useState<string | null>(null)
  const pathname = usePathname()
  const { ready, isError, can } = useAccess()
  const area = areaForPath(pathname)
  const locked = ready && area !== null && !can(area)

  // The default landing page (/today) belongs to the brain: send users
  // whose plan doesn't include it to their own home page instead.
  useEffect(() => {
    if (locked && pathname === '/today') router.replace(homePath(can))
  }, [locked, pathname, can, router])

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
      {/* MarketIndicator moved into LeftNav sidebar as a dot + hover panel */}
      {/* Children render ONCE. Mobile: full width + bottom padding for the
          BottomNav. md+: offset for the floating LeftNav rail. (Rendering
          separate desktop/mobile copies mounted every page twice.) */}
      <div className="md:ml-[72px]">
        <main id="main-content" className="max-w-[1440px] mx-auto px-4 pt-6 pb-24 md:px-6 md:pb-6 lg:px-8">
          {/* Wait for /auth/me before showing a gated page, so a locked
              page never flashes (or fires API calls that would 403). */}
          <div className="min-w-0">{!ready && !isError && area !== null ? null : locked ? <LockedArea feature={area} /> : children}</div>
        </main>
      </div>
      <BottomNav />
      {/* Last login — fixed bottom right */}
      {lastLogin && (
        <div className="hidden md:block fixed bottom-4 right-6 z-40">
          <span className="text-[10px]" style={{ color: theme.colors.textHint }}>
            {t.overview.lastLogin} {new Date(lastLogin).toLocaleString(intlLocale(), {
              month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
              timeZone: 'America/New_York', timeZoneName: 'short',
            })}
          </span>
        </div>
      )}
    </>
  )
}
