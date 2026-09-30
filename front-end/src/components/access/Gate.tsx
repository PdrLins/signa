'use client'

import type { ReactNode } from 'react'
import { useAccess } from '@/hooks/useAccess'

/** Renders children only when the user may use `feature` (an area or
 *  action key from GET /auth/me). The server enforces the same key; this
 *  only keeps unusable buttons and panels out of sight. */
export function Gate({ feature, children, fallback = null }: {
  feature: string
  children: ReactNode
  fallback?: ReactNode
}) {
  const { can } = useAccess()
  return <>{can(feature) ? children : fallback}</>
}
