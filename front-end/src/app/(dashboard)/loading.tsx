'use client'

import { Skeleton } from '@/components/ui/Skeleton'

export default function DashboardLoading() {
  return (
    <div style={{ padding: 24, display: 'flex', flexDirection: 'column', gap: 16 }}>
      <Skeleton width="40%" height={28} borderRadius={6} />
      <Skeleton width="100%" height={120} borderRadius={12} />
      <Skeleton width="100%" height={120} borderRadius={12} />
      <Skeleton width="100%" height={80} borderRadius={12} />
    </div>
  )
}
