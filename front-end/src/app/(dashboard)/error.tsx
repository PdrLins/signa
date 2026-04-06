'use client'

import { ErrorDisplay } from '@/components/ui/ErrorDisplay'

export default function DashboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  return <ErrorDisplay message={error.message} onRetry={reset} />
}
