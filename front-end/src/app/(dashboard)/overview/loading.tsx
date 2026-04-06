'use client'

import { Skeleton } from '@/components/ui/Skeleton'

export default function OverviewLoading() {
  return (
    <div style={{ padding: 24, display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Stats bar */}
      <div style={{ display: 'flex', gap: 12 }}>
        {[1, 2, 3, 4].map((i) => (
          <Skeleton key={i} width="25%" height={80} borderRadius={12} />
        ))}
      </div>
      {/* Quick actions */}
      <Skeleton width="100%" height={56} borderRadius={12} />
      {/* Signal cards */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {[1, 2, 3].map((i) => (
          <Skeleton key={i} width="100%" height={100} borderRadius={12} />
        ))}
      </div>
    </div>
  )
}
