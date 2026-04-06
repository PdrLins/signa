'use client'

import { Skeleton } from '@/components/ui/Skeleton'

export default function SignalsLoading() {
  return (
    <div style={{ padding: 24, display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Header + filter bar */}
      <Skeleton width="30%" height={28} borderRadius={6} />
      <div style={{ display: 'flex', gap: 8 }}>
        {[1, 2, 3].map((i) => (
          <Skeleton key={i} width={80} height={32} borderRadius={16} />
        ))}
      </div>
      {/* Signal cards */}
      {[1, 2, 3, 4, 5].map((i) => (
        <Skeleton key={i} width="100%" height={88} borderRadius={12} />
      ))}
    </div>
  )
}
