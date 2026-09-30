'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { holdingsApi, CheckApiError } from '@/lib/api'
import { ApiAccessError } from '@/lib/access'
import { isMarketOpen } from '@/lib/utils'
import type { HoldingsResponse, ReviewJob } from '@/types/holdings'
import type { Scope } from '@/types/tracker'

export const HOLDINGS_KEY = ['holdings'] as const
export const ALLOCATE_KEY = ['holdings', 'allocate'] as const

export interface HoldingsError {
  code: string
  message: string
  status: number
  nextAllowedAt?: string
  /** slot_limit: the plan's number of followed stocks */
  limit?: number
  /** the rest of the error body (e.g. holdings, errors, summary) */
  extra?: Record<string, unknown>
}

export function toHoldingsError(e: unknown): HoldingsError {
  if (e instanceof ApiAccessError) {
    return { code: e.code, message: e.message, status: 403, limit: e.limit }
  }
  if (e instanceof CheckApiError) {
    return { code: e.code, message: e.message, status: e.status, nextAllowedAt: (e as { nextAllowedAt?: string }).nextAllowedAt, extra: e.extra }
  }
  const msg = e instanceof Error ? e.message : String(e)
  return { code: /network/i.test(msg) ? 'network' : 'internal', message: msg, status: 0 }
}

/** GET /holdings (optionally one account) — polls every 5s while the
 *  monitor (price refresh) runs. */
export function useHoldings(scope: Scope = {}) {
  const accountId = scope.account_id ?? null
  const personId = scope.person_id ?? null
  return useQuery<HoldingsResponse, unknown>({
    queryKey: [...HOLDINGS_KEY, 'list', accountId ?? 'all', personId ?? 'all'],
    queryFn: () => holdingsApi.list(accountId || personId
      ? { ...(accountId ? { account_id: accountId } : {}), ...(personId ? { person_id: personId } : {}) }
      : undefined),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
    retry: (count, err) => !(err instanceof CheckApiError && err.status === 503) && count < 2,
    // 5s while the monitor refreshes; else live prices every 60s in market
    // hours / 5 min outside (paused while the tab is hidden).
    refetchInterval: (q) => (q.state.data?.monitor_running ? 5_000 : isMarketOpen() ? 60_000 : 5 * 60_000),
    refetchIntervalInBackground: false,
  })
}

export function useAllocateIdeas(enabled: boolean, includeWatchlist: boolean) {
  return useQuery({
    queryKey: [...ALLOCATE_KEY, includeWatchlist],
    queryFn: () => holdingsApi.allocate(includeWatchlist),
    enabled,
    staleTime: 5 * 60_000,
  })
}

const POLL_MS = 2_000

/** Review jobs: start ({ids} | {all}) and poll until done; resumes a running
 *  job after a reload. Invalidates holdings + allocate ideas as results land. */
export function useHoldingsReview(enabled = true) {
  const qc = useQueryClient()
  const [job, setJob] = useState<ReviewJob | null>(null)
  const [error, setError] = useState<HoldingsError | null>(null)
  const [starting, setStarting] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const lastDone = useRef(0)

  const stop = useCallback(() => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = null
  }, [])

  const refreshData = useCallback(() => {
    qc.invalidateQueries({ queryKey: HOLDINGS_KEY })
  }, [qc])

  const follow = useCallback((j: ReviewJob) => {
    setJob(j)
    if (j.done !== lastDone.current) {
      lastDone.current = j.done
      refreshData()
    }
    if (j.status !== 'running') {
      stop()
      refreshData()
      return
    }
    timer.current = setTimeout(async () => {
      try {
        follow(await holdingsApi.reviewJob(j.job_id))
      } catch (e) {
        setError(toHoldingsError(e))
      }
    }, POLL_MS)
  }, [refreshData, stop])

  useEffect(() => {
    if (!enabled) return
    let alive = true
    holdingsApi.reviewCurrent()
      .then((r) => { if (alive && r.job && r.job.status === 'running') follow(r.job) })
      .catch(() => {})
    return () => { alive = false; stop() }
  }, [follow, stop, enabled])

  const start = useCallback(async (body: { ids?: string[]; all?: boolean }) => {
    stop()
    setError(null)
    setStarting(true)
    lastDone.current = 0
    try {
      follow(await holdingsApi.review(body))
    } catch (e) {
      setError(toHoldingsError(e))
    } finally {
      setStarting(false)
    }
  }, [follow, stop])

  const running = starting || job?.status === 'running'
  return { job, error, running, starting, start, clearError: () => setError(null) }
}
