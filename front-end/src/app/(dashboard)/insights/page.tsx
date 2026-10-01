'use client'

import { Suspense, useEffect } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'

export default function InsightsPage() {
  return (
    <Suspense fallback={null}>
      <InsightsRedirect />
    </Suspense>
  )
}

/** Performance and Allocation now live as tabs on /holdings. Old links
 *  (?tab=allocation, ?account_id=…) keep working. */
function InsightsRedirect() {
  const router = useRouter()
  const params = useSearchParams()
  useEffect(() => {
    const q = new URLSearchParams(params.toString())
    q.set('tab', params.get('tab') === 'allocation' ? 'allocation' : 'performance')
    router.replace(`/holdings?${q.toString()}`)
  }, [params, router])
  return null
}
