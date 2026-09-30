'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { holdingsApi, CheckApiError } from '@/lib/api'
import { ApiAccessError } from '@/lib/access'
import type { HoldingsResponse, ReviewJob } from '@/types/holdings'

export const HOLDINGS_KEY = ['holdings'] as const
export const ALLOCATE_KEY = ['holdings', 'allocate'] as const

export interface HoldingsError {
  code: string
  message: string
  status: number
  nextAllowedAt?: string
  /** slot_limit: the plan's number of followed stocks */
  limit?: number
}

export function toHoldingsError(e: unknown): HoldingsError {
  if (e instanceof ApiAccessError) {
    return { code: e.code, message: e.message, status: 403, limit: e.limit }
  }
  if (e instanceof CheckApiError) {
    return { code: e.code, message: e.message, status: e.status, nextAllowedAt: (e as { nextAllowedAt?: string }).nextAllowedAt }
  }
  const msg = e instanceof Error ? e.message : String(e)
  return { code: /network/i.test(msg) ? 'network' : 'internal', message: msg, status: 0 }
}

/** GET /holdings — polls every 5s while the monitor (price refresh) runs. */
export function useHoldings() {
  return useQuery<HoldingsResponse, unknown>({
    queryKey: HOLDINGS_KEY,
    queryFn: () => holdingsApi.list(),
    staleTime: 30_000,
    retry: (count, err) => !(err instanceof CheckApiError && err.status === 503) && count < 2,
    refetchInterval: (q) => (q.state.data?.monitor_running ? 5_000 : false),
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
