'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { checkApi, CheckApiError } from '@/lib/api'
import type { AnyCheckResult, CheckJob, CheckJobError, CheckMode } from '@/types/check'

const POLL_MS = 2_000

export interface StockCheckState {
  job: CheckJob | null
  result: AnyCheckResult | null
  error: CheckJobError | null
  running: boolean
  /** the ticker the user asked for (as typed) */
  ticker: string | null
  mode: CheckMode
}

const IDLE: StockCheckState = { job: null, result: null, error: null, running: false, ticker: null, mode: 'short' }

function toError(e: unknown): CheckJobError {
  if (e instanceof CheckApiError) return { code: e.code, message: e.message, status: e.status }
  const msg = e instanceof Error ? e.message : String(e)
  return { code: /network/i.test(msg) ? 'network' : 'internal', message: msg, status: 0 }
}

/** POST /check ({ticker, force, mode}), then poll GET /check/{id} every 2s until done or failed. */
export function useStockCheck(onDone?: (r: AnyCheckResult) => void) {
  const [state, setState] = useState<StockCheckState>(IDLE)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const runId = useRef(0)
  // The backend keeps jobs in memory: a restart (e.g. dev auto-reload) loses
  // them and polling gets 404 job_not_found. Re-submit the same check once.
  const lastRequest = useRef<{ ticker: string; force: boolean; mode: CheckMode } | null>(null)
  const restarts = useRef(0)
  const onDoneRef = useRef(onDone)
  onDoneRef.current = onDone

  const stop = useCallback(() => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = null
  }, [])

  useEffect(() => stop, [stop])

  const settle = useCallback((job: CheckJob, id: number) => {
    if (id !== runId.current) return
    if (job.status === 'running') {
      setState((s) => ({ ...s, job, running: true }))
      timer.current = setTimeout(async () => {
        try {
          const next = await checkApi.get(job.job_id)
          settle(next, id)
        } catch (e) {
          if (id !== runId.current) return
          const err = toError(e)
          const req = lastRequest.current
          if (err.code === 'job_not_found' && req && restarts.current < 1) {
            restarts.current += 1
            try {
              const again = await checkApi.start(req.ticker, req.force, req.mode)
              settle(again, id)
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
    if (job.status === 'done' && job.result) {
      setState((s) => ({ ...s, job, result: job.result ?? null, running: false, error: null }))
      onDoneRef.current?.(job.result)
      return
    }
    setState((s) => ({
      ...s, job, running: false,
      error: job.error ?? { code: 'internal', message: 'The check failed.', status: 500 },
    }))
  }, [])

  const start = useCallback(async (ticker: string, force = false, mode: CheckMode = 'short') => {
    stop()
    const id = ++runId.current
    const clean = ticker.trim()
    lastRequest.current = { ticker: clean, force, mode }
    restarts.current = 0
    setState({ ...IDLE, running: true, ticker: clean, mode })
    try {
      const job = await checkApi.start(clean, force, mode)
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
