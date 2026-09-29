'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { checkApi, CheckApiError } from '@/lib/api'
import type { CheckJobError, CheckMode, CompareJob } from '@/types/check'

const POLL_MS = 2_000

export interface CompareError extends CheckJobError {
  extra?: Record<string, unknown>
}

export interface StockCompareState {
  job: CompareJob | null
  error: CompareError | null
  running: boolean
  tickers: string[]
  mode: CheckMode
}

const IDLE: StockCompareState = { job: null, error: null, running: false, tickers: [], mode: 'short' }

function toError(e: unknown): CompareError {
  if (e instanceof CheckApiError) return { code: e.code, message: e.message, status: e.status, extra: e.extra }
  const msg = e instanceof Error ? e.message : String(e)
  return { code: /network/i.test(msg) ? 'network' : 'internal', message: msg, status: 0 }
}

/** POST /check/compare, then poll GET /check/compare/{id} every 2s until done.
 *  A 404 while polling (the in-memory job was lost to a back-end restart)
 *  re-submits the same comparison once, like useStockCheck. */
export function useStockCompare(onDone?: (job: CompareJob) => void) {
  const [state, setState] = useState<StockCompareState>(IDLE)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const runId = useRef(0)
  const lastRequest = useRef<{ tickers: string[]; force: boolean; mode: CheckMode } | null>(null)
  const restarts = useRef(0)
  const onDoneRef = useRef(onDone)
  onDoneRef.current = onDone

  const stop = useCallback(() => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = null
  }, [])

  useEffect(() => stop, [stop])

  const settle = useCallback((job: CompareJob, id: number) => {
    if (id !== runId.current) return
    if (job.status !== 'done') {
      setState((s) => ({ ...s, job: { ...job, remaining_today: job.remaining_today ?? s.job?.remaining_today }, running: true }))
      timer.current = setTimeout(async () => {
        try {
          const next = await checkApi.compareGet(job.compare_id)
          settle(next, id)
        } catch (e) {
          if (id !== runId.current) return
          const err = toError(e)
          const req = lastRequest.current
          if ((err.code === 'compare_not_found' || err.code === 'job_not_found') && req && restarts.current < 1) {
            restarts.current += 1
            try {
              const again = await checkApi.compareStart(req.tickers, req.force, req.mode)
              settle({ ...again, remaining_today: again.remaining_today ?? job.remaining_today }, id)
              return
            } catch (e2) {
              if (id !== runId.current) return
              setState((s) => ({ ...s, running: false, error: toError(e2) }))
              return
            }
          }
          setState((s) => ({ ...s, running: false, error: err }))
        }
      }, POLL_MS)
      return
    }
    setState((s) => ({
      ...s,
      job: { ...job, remaining_today: job.remaining_today ?? s.job?.remaining_today },
      running: false,
      error: null,
    }))
    onDoneRef.current?.(job)
  }, [])

  const start = useCallback(async (tickers: string[], force = false, mode: CheckMode = 'short') => {
    stop()
    const id = ++runId.current
    const clean = tickers.map((t) => t.trim()).filter(Boolean)
    lastRequest.current = { tickers: clean, force, mode }
    restarts.current = 0
    setState({ ...IDLE, running: true, tickers: clean, mode })
    try {
      const job = await checkApi.compareStart(clean, force, mode)
      settle(job, id)
    } catch (e) {
      if (id !== runId.current) return
      setState((s) => ({ ...s, running: false, error: toError(e) }))
    }
  }, [settle, stop])

  const reset = useCallback(() => {
    stop()
    runId.current++
    setState(IDLE)
  }, [stop])

  return { ...state, start, reset }
}
