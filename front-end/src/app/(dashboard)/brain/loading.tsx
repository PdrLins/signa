'use client'

import { Skeleton } from '@/components/ui/Skeleton'

export default function BrainLoading() {
  return (
    <div style={{ padding: 24, display: 'flex', flexDirection: 'column', gap: 16 }}>
      <Skeleton width="25%" height={28} borderRadius={6} />
      <Skeleton width="100%" height={160} borderRadius={12} />
      <Skeleton width="100%" height={200} borderRadius={12} />
    </div>
  )
}
