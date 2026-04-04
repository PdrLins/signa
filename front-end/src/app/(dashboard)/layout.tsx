'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuthStore } from '@/store/authStore'
import { TopNav } from '@/components/layout/TopNav'
import { BottomNav } from '@/components/layout/BottomNav'
import { Sidebar } from '@/components/layout/Sidebar'

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const token = useAuthStore((s) => s.token)
  const setToken = useAuthStore((s) => s.setToken)

  // Hydrate from localStorage on mount (covers race with StoreInitializer)
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
      <TopNav />
      <main className="max-w-[1280px] mx-auto px-4 lg:px-8 py-6 pb-24 md:pb-6">
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-8">
          <div className="min-w-0">{children}</div>
          <Sidebar />
        </div>
      </main>
      <BottomNav />
    </>
  )
}
