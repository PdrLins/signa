'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useTheme } from '@/hooks/useTheme'
import { useAuthStore } from '@/store/authStore'
import { useI18nStore } from '@/store/i18nStore'
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
