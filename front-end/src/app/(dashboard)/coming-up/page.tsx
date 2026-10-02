'use client'

import { Suspense } from 'react'
import { useI18nStore } from '@/store/i18nStore'
import { useScope } from '@/hooks/usePortfolioInsights'
import { HomeHeader } from '@/components/home/HomeHeader'
import { EventsTimeline } from '@/components/tracker/EventsTimeline'
import { ScopeSelect } from '@/components/tracker/ui'

export default function ComingUpPage() {
  return (
    <Suspense fallback={null}>
      <ComingUpInner />
    </Suspense>
  )
}

/** Coming up: dividends, earnings, rate decisions and fired alerts for the
 *  stocks the user owns and follows (GET /events/upcoming). Its own page;
 *  reached from the Home bell, Home's Coming up card and Dividends. */
function ComingUpInner() {
  const t = useI18nStore((s) => s.t)
  const { scope, setScope } = useScope()
  return (
    <div className="space-y-4 pb-4 min-w-0 max-w-3xl">
      <HomeHeader title={t.comingUpPage.title} />
      <ScopeSelect scope={scope} onChange={setScope} />
      <EventsTimeline />
    </div>
  )
}
