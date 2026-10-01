'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'

/** Settings merged into Profile (theme, language, sign-out). The owner's
 *  brain configuration lives at /brain/settings, linked from Profile. */
export default function SettingsRedirect() {
  const router = useRouter()
  useEffect(() => { router.replace('/profile') }, [router])
  return null
}
