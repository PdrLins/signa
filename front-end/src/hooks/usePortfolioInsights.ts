'use client'

import { useCallback, useEffect, useMemo } from 'react'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { portfolioInsightsApi, CheckApiError } from '@/lib/api'
import { ApiAccessError } from '@/lib/access'
import { useI18nStore } from '@/store/i18nStore'
import { usePrivacyStore } from '@/store/privacyStore'
import { money } from '@/components/holdings/format'
import { isMarketOpen } from '@/lib/utils'
import type {
  Allocation, AllocationPlan, AllocationTargets, DividendSummary, HistoryRange, IncomeQuality,
  PortfolioHistory, PortfolioPerformance, PortfolioSummary, Scope, UpcomingEvents,
} from '@/types/tracker'

export const INSIGHTS_KEY = ['portfolio-insights'] as const

/** Coded answers (4xx/503) and plan limits (403) won't change on retry. */
function retry(count: number, err: unknown): boolean {
  if (err instanceof CheckApiError || err instanceof ApiAccessError) return false
  return count < 2
}

/** Live polling: every 60s while the market is open (the back-end refreshes
 *  quotes every 60s at best), every 5 min otherwise. React Query pauses the
 *  interval while the tab is hidden (refetchIntervalInBackground = false). */
export function livePollMs(): number {
  return isMarketOpen() ? 60_000 : 5 * 60_000
}

function scopeKey(scope: Scope): string {
  return `${scope.account_id ?? ''}|${scope.person_id ?? ''}`
}

/** Account / person scope stored in the URL (?account_id= / ?person_id=). */
export function useScope() {
  const params = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()
  const accountId = params.get('account_id') || undefined
  const personId = params.get('person_id') || undefined
  const scope = useMemo<Scope>(() => ({ account_id: accountId, person_id: personId }), [accountId, personId])
  /** "?account_id=…" (or '') to carry the scope onto links. */
  const query = useMemo(() => {
    const q = new URLSearchParams()
    if (accountId) q.set('account_id', accountId)
    if (personId) q.set('person_id', personId)
    const s = q.toString()
    return s ? `?${s}` : ''
  }, [accountId, personId])
  const setScope = useCallback((next: Scope) => {
    const q = new URLSearchParams(params.toString())
    q.delete('account_id')
    q.delete('person_id')
    if (next.account_id) q.set('account_id', next.account_id)
    if (next.person_id) q.set('person_id', next.person_id)
    const s = q.toString()
    router.replace(s ? `${pathname}?${s}` : pathname, { scroll: false })
  }, [params, pathname, router])
  return { scope, query, setScope, scoped: !!(accountId || personId) }
}

/** Money in the home currency, masked when the eye toggle hides amounts. */
export function useMoney(currency: string | null | undefined) {
  const locale = useI18nStore((s) => s.locale)
  const hidden = usePrivacyStore((s) => s.hidden)
  const load = usePrivacyStore((s) => s.load)
  useEffect(() => { load() }, [load])
  const fmt = useCallback((v: number | null | undefined, digits = 2) =>
    hidden ? '••••' : money(v, currency ?? 'CAD', locale, digits), [hidden, currency, locale])
  const signed = useCallback((v: number | null | undefined, digits = 2) => {
    if (hidden) return '••••'
    const s = money(v, currency ?? 'CAD', locale, digits)
    return v !== null && v !== undefined && Number.isFinite(v) && v > 0 ? `+${s}` : s
  }, [hidden, currency, locale])
  return { fmt, signed, hidden }
}

export function usePortfolioSummary(scope: Scope, enabled = true) {
  return useQuery<PortfolioSummary, unknown>({
    queryKey: [...INSIGHTS_KEY, 'summary', scopeKey(scope)],
    queryFn: () => portfolioInsightsApi.summary(scope),
    staleTime: 30_000,
    refetchInterval: livePollMs,
    refetchIntervalInBackground: false,
    placeholderData: keepPreviousData,
    enabled,
    retry,
  })
}

export function usePortfolioHistory(scope: Scope, range: HistoryRange, compare: string | null, enabled = true) {
  return useQuery<PortfolioHistory, unknown>({
    queryKey: [...INSIGHTS_KEY, 'history', scopeKey(scope), range, compare ?? ''],
    queryFn: () => portfolioInsightsApi.history(scope, range, compare),
    staleTime: range === '1D' ? 30_000 : 5 * 60_000,
    refetchInterval: range === '1D' ? livePollMs : false,
    refetchIntervalInBackground: false,
    placeholderData: keepPreviousData,
    enabled,
    retry,
  })
}

export function usePortfolioPerformance(scope: Scope, range: HistoryRange, compare: string | null, enabled = true) {
  return useQuery<PortfolioPerformance, unknown>({
    queryKey: [...INSIGHTS_KEY, 'performance', scopeKey(scope), range, compare ?? ''],
    queryFn: () => portfolioInsightsApi.performance(scope, range, compare),
    staleTime: 5 * 60_000,
    placeholderData: keepPreviousData,
    enabled,
    retry,
  })
}

export function useAllocation(scope: Scope, enabled = true) {
  return useQuery<Allocation, unknown>({
    queryKey: [...INSIGHTS_KEY, 'allocation', scopeKey(scope)],
    queryFn: () => portfolioInsightsApi.allocation(scope),
    staleTime: 2 * 60_000,
    placeholderData: keepPreviousData,
    enabled,
    retry,
  })
}

export function useAllocationPlan(scope: Scope, amount: number | null, enabled = true) {
  return useQuery<AllocationPlan, unknown>({
    queryKey: [...INSIGHTS_KEY, 'plan', scopeKey(scope), amount ?? 0],
    queryFn: () => portfolioInsightsApi.plan(scope, amount ?? 0),
    staleTime: 2 * 60_000,
    enabled: enabled && !!amount && amount > 0,
    retry,
  })
}

/** PUT targets; refreshes allocation + plans. */
export function useSaveTargets() {
  const qc = useQueryClient()
  return useMutation<AllocationTargets, unknown, AllocationTargets['targets']>({
    mutationFn: (targets) => portfolioInsightsApi.putTargets(targets),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [...INSIGHTS_KEY, 'allocation'] })
      qc.invalidateQueries({ queryKey: [...INSIGHTS_KEY, 'plan'] })
    },
  })
}

export function useDividendSummary(scope: Scope, period: string, enabled = true) {
  return useQuery<DividendSummary, unknown>({
    queryKey: [...INSIGHTS_KEY, 'dividends', scopeKey(scope), period],
    queryFn: () => portfolioInsightsApi.dividendSummary(scope, period),
    staleTime: 5 * 60_000,
    placeholderData: keepPreviousData,
    enabled,
    retry,
  })
}

export function useIncomeQuality(symbol: string, enabled = true) {
  return useQuery<IncomeQuality, unknown>({
    queryKey: [...INSIGHTS_KEY, 'income-quality', symbol],
    queryFn: () => portfolioInsightsApi.incomeQuality(symbol),
    staleTime: 30 * 60_000,
    enabled: enabled && !!symbol,
    retry,
  })
}

export function useUpcomingEvents(scope: Scope, days: number, enabled = true) {
  return useQuery<UpcomingEvents, unknown>({
    queryKey: [...INSIGHTS_KEY, 'events', scopeKey(scope), days],
    queryFn: () => portfolioInsightsApi.upcomingEvents(scope, days),
    staleTime: 5 * 60_000,
    placeholderData: keepPreviousData,
    enabled,
    retry,
  })
}
