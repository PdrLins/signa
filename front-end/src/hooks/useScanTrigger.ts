import { useState, useEffect, useCallback } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { scansApi, type ScanProgress } from '@/lib/api'
import { useToast } from '@/hooks/useToast'
import { useI18nStore } from '@/store/i18nStore'

/**
 * "Scan now" action + progress polling (every 2.5s until COMPLETE/FAILED).
 * Shared by /signals and /today. On completion every query that depends on
 * scan output (signals, scans, stats, insights) is invalidated.
 */
export function useScanTrigger() {
  const t = useI18nStore((s) => s.t)
  const toast = useToast()
  const queryClient = useQueryClient()
  const [scanId, setScanId] = useState<string | null>(null)
  const [progress, setProgress] = useState<ScanProgress | null>(null)
  const [cooldown, setCooldown] = useState(false)
  const scanning = !!scanId

  useEffect(() => {
    if (!scanId) return
    let cancelled = false
    const poll = async () => {
      try {
        const p = await scansApi.getProgress(scanId)
        if (cancelled) return
        setProgress(p)
        if (p.status === 'COMPLETE') {
          toast.show(
            t.signals.scanComplete.replace('{signals}', String(p.signals_found)).replace('{gems}', String(p.gems_found)),
            'success',
            5000,
          )
          setScanId(null)
          setProgress(null)
          queryClient.invalidateQueries({ queryKey: ['signals'] })
          queryClient.invalidateQueries({ queryKey: ['scans'] })
          queryClient.invalidateQueries({ queryKey: ['stats'] })
          queryClient.invalidateQueries({ queryKey: ['insights'] })
        } else if (p.status === 'FAILED') {
          toast.show(p.error_message || t.signals.scanFailedGeneric, 'error')
          setScanId(null)
          setProgress(null)
        }
      } catch {
        // Ignore polling errors, retry next interval
      }
    }
    poll()
    const interval = setInterval(poll, 2500)
    return () => { cancelled = true; clearInterval(interval) }
  // eslint-disable-next-line react-hooks/exhaustive-deps -- t.signals refs are stable across renders
  }, [scanId, queryClient, toast])

  const trigger = useCallback(async () => {
    if (scanning || cooldown) return
    setCooldown(true)
    setTimeout(() => setCooldown(false), 5000) // 5s cooldown between scans
    try {
      const res = await scansApi.trigger('MANUAL')
      setScanId(res.scan_id)
      toast.show(t.signals.scanStarted, 'info', 3000)
    } catch {
      toast.show(t.signals.scanFailed, 'error')
    }
  }, [scanning, cooldown, toast, t])

  const phaseLabel = useCallback((phase: string) => {
    const p = t.signals.phases
    const map: Record<string, string> = {
      queued: p.queued,
      loading: p.loading,
      screening: p.screening,
      filtering: p.filtering,
      macro: p.macro,
      prescoring: p.prescoring,
      analyzing: progress?.current_ticker ? `${p.analyzing} ${progress.current_ticker}...` : p.analyzing,
      saving: p.saving,
      alerting: p.alerting,
      monitoring: p.monitoring,
      complete: p.complete,
    }
    return map[phase] || phase
  }, [t, progress?.current_ticker])

  return { scanning, progress, cooldown, trigger, phaseLabel }
}
