'use client'

import { Suspense, useCallback } from 'react'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useScope } from '@/hooks/usePortfolioInsights'
import { HomeHeader } from '@/components/home/HomeHeader'
import { PerformanceTab } from '@/components/tracker/PerformanceTab'
import { AllocationTab } from '@/components/tracker/AllocationTab'
import { ScopeSelect } from '@/components/tracker/ui'

type Tab = 'performance' | 'allocation'
const TABS: Tab[] = ['performance', 'allocation']

export default function InsightsPage() {
  return (
    <Suspense fallback={null}>
      <InsightsInner />
    </Suspense>
  )
}

function InsightsInner() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const ti = t.insightsPage
  const params = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()
  const { scope, setScope, scoped } = useScope()
  const tab: Tab = params.get('tab') === 'allocation' ? 'allocation' : 'performance'
  const setTab = useCallback((next: Tab) => {
    const q = new URLSearchParams(params.toString())
    if (next === 'performance') q.delete('tab')
    else q.set('tab', next)
    const s = q.toString()
    router.replace(s ? `${pathname}?${s}` : pathname, { scroll: false })
  }, [params, pathname, router])

  return (
    <div className="space-y-4 pb-4 min-w-0">
      <HomeHeader title={ti.title} />
      <p className="text-[13px] max-w-2xl" style={{ color: theme.colors.textSub }}>{ti.subtitle}</p>
      <ScopeSelect scope={scope} onChange={setScope} />
      <div role="tablist" aria-label={ti.tabsLabel} className="flex gap-2">
        {TABS.map((k) => {
          const on = tab === k
          return (
            <button key={k} type="button" role="tab" id={`insights-tab-${k}`} aria-selected={on} aria-controls="insights-panel"
              tabIndex={on ? 0 : -1} onClick={() => setTab(k)}
              onKeyDown={(e) => {
                if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') setTab(k === 'performance' ? 'allocation' : 'performance')
              }}
              className="min-h-[44px] px-4 rounded-full text-[14px] font-semibold focus-visible:outline focus-visible:outline-2"
              style={{
                backgroundColor: on ? theme.colors.primary : theme.colors.surfaceAlt,
                color: on ? theme.colors.surface : theme.colors.text,
                outlineColor: theme.colors.primary,
              }}>
              {ti.tabs[k]}
            </button>
          )
        })}
      </div>
      <div role="tabpanel" id="insights-panel" aria-labelledby={`insights-tab-${tab}`} className="min-w-0">
        {tab === 'performance' ? <PerformanceTab scope={scope} /> : <AllocationTab scope={scope} scoped={scoped} />}
      </div>
      <p className="text-[12px]" style={{ color: theme.colors.textHint }}>{t.tracker.notAdvice}</p>
    </div>
  )
}
