'use client'

import { useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

export function QueryProvider({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30 * 1000,
            // Don't retry auth failures — the interceptor handles logout.
            // Retry once for genuine network/server errors only.
            retry: (failureCount, error) => {
              const msg = (error as Error)?.message || ''
              if (msg.includes('Not authenticated') || msg.includes('Logging out')) return false
              return failureCount < 1
            },
            refetchOnWindowFocus: false,
          },
        },
      })
  )

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}
