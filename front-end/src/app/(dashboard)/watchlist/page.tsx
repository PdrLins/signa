'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'

/** The watchlist is now the Following tab. */
export default function WatchlistRedirect() {
  const router = useRouter()
  useEffect(() => { router.replace('/following') }, [router])
  return null
}
