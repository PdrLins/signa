'use client'

import { Skeleton } from '@/components/ui/Skeleton'

export default function SettingsLoading() {
  return (
    <div style={{ padding: 24, display: 'flex', flexDirection: 'column', gap: 16 }}>
      <Skeleton width="25%" height={28} borderRadius={6} />
      {/* Settings sections */}
      {[1, 2, 3, 4].map((i) => (
        <Skeleton key={i} width="100%" height={72} borderRadius={12} />
      ))}
    </div>
  )
}
