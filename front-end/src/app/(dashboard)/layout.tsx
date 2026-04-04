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

  useEffect(() => {
    if (!isAuthenticated && !localStorage.getItem('signa-token')) {
      router.push('/login')
    }
  }, [isAuthenticated, router])

  if (!isAuthenticated && !token) {
    return null
  }

  return (
    <>
      <TopNav />
      <main className="max-w-[1080px] mx-auto px-4 py-6 pb-24 md:pb-6">
        <div className="grid grid-cols-1 md:grid-cols-[1fr_288px] gap-6">
          <div className="min-w-0">{children}</div>
          <Sidebar />
        </div>
      </main>
      <BottomNav />
    </>
  )
}
