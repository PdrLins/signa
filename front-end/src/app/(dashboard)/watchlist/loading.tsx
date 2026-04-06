'use client'

import { Skeleton } from '@/components/ui/Skeleton'

export default function WatchlistLoading() {
  return (
    <div style={{ padding: 24, display: 'flex', flexDirection: 'column', gap: 16 }}>
      <Skeleton width="30%" height={28} borderRadius={6} />
      {/* Table header */}
      <Skeleton width="100%" height={40} borderRadius={8} />
      {/* Table rows */}
      {[1, 2, 3, 4, 5, 6].map((i) => (
        <Skeleton key={i} width="100%" height={56} borderRadius={8} />
      ))}
    </div>
  )
}
