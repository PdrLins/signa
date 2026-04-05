'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuthStore } from '@/store/authStore'
import { LeftNav } from '@/components/layout/LeftNav'
import { BottomNav } from '@/components/layout/BottomNav'
import { Sidebar } from '@/components/layout/Sidebar'

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const token = useAuthStore((s) => s.token)
  const setToken = useAuthStore((s) => s.setToken)

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
          <div className="grid grid-cols-1 lg:grid-cols-[1fr_300px] gap-6">
            <div className="min-w-0">{children}</div>
            <Sidebar />
          </div>
        </main>
      </div>
      {/* Mobile: full width */}
      <div className="md:hidden">
        <main className="px-4 py-6 pb-24">
          {children}
        </main>
      </div>
      <BottomNav />
    </>
  )
}
