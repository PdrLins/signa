'use client'

import { Suspense, useEffect } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'

export default function ComingUpPage() {
  return (
    <Suspense fallback={null}>
      <ComingUpRedirect />
    </Suspense>
  )
}

/** Coming up is now a tab of the Dividends page (scope kept). */
function ComingUpRedirect() {
  const router = useRouter()
  const params = useSearchParams()
  useEffect(() => {
    const q = new URLSearchParams(params.toString())
    q.set('tab', 'upcoming')
    router.replace(`/dividends?${q.toString()}`)
  }, [params, router])
  return null
}
