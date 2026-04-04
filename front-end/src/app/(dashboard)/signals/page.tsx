'use client'

import { useState, useEffect, useCallback } from 'react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useQueryClient } from '@tanstack/react-query'
import { useAllSignals } from '@/hooks/useSignals'
import { scansApi, type ScanProgress } from '@/lib/api'
import { SignalList } from '@/components/signals/SignalList'
import { Button } from '@/components/ui/Button'
import { ProgressBar } from '@/components/ui/ProgressBar'
import { useToast } from '@/hooks/useToast'
import type { SignalFilters } from '@/types/signal'

export default function SignalsPage() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const toast = useToast()
  const queryClient = useQueryClient()
  const [bucket, setBucket] = useState<string>('All')
  const [assetType, setAssetType] = useState<string>('All')
  const [minScore, setMinScore] = useState<number>(0)
  const [scanId, setScanId] = useState<string | null>(null)
  const [progress, setProgress] = useState<ScanProgress | null>(null)
  const scanning = !!scanId

  // Poll scan progress
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
            `Scan complete: ${p.signals_found} signals, ${p.gems_found} GEMs`,
            'success',
            5000,
          )
          setScanId(null)
          setProgress(null)
          queryClient.invalidateQueries({ queryKey: ['signals'] })
          queryClient.invalidateQueries({ queryKey: ['scans'] })
          queryClient.invalidateQueries({ queryKey: ['stats'] })
        } else if (p.status === 'FAILED') {
          toast.show(p.error_message || 'Scan failed', 'error')
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
  }, [scanId, queryClient, toast])

  const handleScanNow = useCallback(async () => {
    if (scanning) return
    try {
      const res = await scansApi.trigger('MORNING')
      setScanId(res.scan_id)
      toast.show('Scan started...', 'info', 3000)
    } catch {
      toast.show(t.signals.scanFailed, 'error')
    }
  }, [scanning, toast, t])

  const filters: SignalFilters = {}
  if (bucket === 'SAFE_INCOME' || bucket === 'HIGH_RISK') filters.bucket = bucket
  if (minScore > 0) filters.min_score = minScore

  const { data: allSignals, isLoading, isError, error } = useAllSignals(
    Object.keys(filters).length ? filters : undefined
  )

  const signals = assetType === 'All'
    ? allSignals
    : allSignals?.filter((s) => s.asset_type === assetType)

  const assetOptions = ['All', 'EQUITY', 'CRYPTO']
  const bucketOptions = ['All', 'SAFE_INCOME', 'HIGH_RISK']
  const scoreOptions = [
    { label: t.signals.anyScore, value: 0 },
    { label: '60+', value: 60 },
    { label: '70+', value: 70 },
    { label: '80+', value: 80 },
  ]

  const phaseLabel = (phase: string) => {
    const map: Record<string, string> = {
      queued: 'Queued...',
      loading: 'Loading universe...',
      screening: 'Screening tickers...',
      filtering: 'Pre-filtering...',
      macro: 'Fetching macro data...',
      analyzing: progress?.current_ticker ? `Analyzing ${progress.current_ticker}...` : 'Analyzing...',
      saving: 'Saving signals...',
      alerting: 'Sending alerts...',
      monitoring: 'Checking positions...',
      complete: 'Complete',
    }
    return map[phase] || phase
  }

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: theme.colors.text }}>
            {t.signals.title}
          </h1>
          {signals && !scanning && (
            <p className="text-sm mt-1" style={{ color: theme.colors.textSub }}>
              {t.signals.showing.replace('{count}', String(signals.length))}
            </p>
          )}
        </div>
        <Button onClick={handleScanNow} disabled={scanning}>
          {scanning ? t.signals.scanning : t.signals.scanNow}
        </Button>
      </div>

      {/* Scan progress bar */}
      {scanning && progress && (
        <div
          className="rounded-xl px-4 py-3 space-y-2"
          style={{ backgroundColor: theme.colors.surfaceAlt, border: `1px solid ${theme.colors.border}` }}
        >
          <div className="flex justify-between items-center">
            <span className="text-xs font-medium" style={{ color: theme.colors.text }}>
              {phaseLabel(progress.phase)}
            </span>
            <span className="text-xs tabular-nums font-semibold" style={{ color: theme.colors.primary }}>
              {progress.progress_pct}%
            </span>
          </div>
          <ProgressBar value={progress.progress_pct} color={theme.colors.primary} height={4} />
          {progress.signals_found > 0 && (
            <p className="text-[11px]" style={{ color: theme.colors.textSub }}>
              {progress.signals_found} signals found{progress.gems_found > 0 ? `, ${progress.gems_found} GEMs` : ''}
            </p>
          )}
        </div>
      )}

      {/* Filter bar */}
      <div className="flex flex-wrap gap-2">
        {/* Asset type */}
        <div className="inline-flex items-center gap-0.5 rounded-lg px-0.5 py-0.5" style={{ backgroundColor: theme.colors.nav }}>
          {assetOptions.map((opt) => {
            const isActive = assetType === opt
            return (
              <button
                key={opt}
                onClick={() => setAssetType(opt)}
                className="px-2.5 py-1 rounded-md text-[11px] font-medium transition-all"
                style={{
                  backgroundColor: isActive ? theme.colors.navActive : 'transparent',
                  color: isActive ? theme.colors.text : theme.colors.textSub,
                }}
              >
                {opt === 'EQUITY' ? t.signals.stocks : opt === 'CRYPTO' ? t.signals.crypto : t.signals.all}
              </button>
            )
          })}
        </div>

        {/* Bucket */}
        <div className="inline-flex items-center gap-0.5 rounded-lg px-0.5 py-0.5" style={{ backgroundColor: theme.colors.nav }}>
          {bucketOptions.map((opt) => {
            const isActive = bucket === opt
            return (
              <button
                key={opt}
                onClick={() => setBucket(opt)}
                className="px-2.5 py-1 rounded-md text-[11px] font-medium transition-all"
                style={{
                  backgroundColor: isActive ? theme.colors.navActive : 'transparent',
                  color: isActive ? theme.colors.text : theme.colors.textSub,
                }}
              >
                {opt === 'SAFE_INCOME' ? t.signals.safeIncome : opt === 'HIGH_RISK' ? t.signals.highRisk : t.signals.all}
              </button>
            )
          })}
        </div>

        {/* Score */}
        <div className="inline-flex items-center gap-0.5 rounded-lg px-0.5 py-0.5" style={{ backgroundColor: theme.colors.nav }}>
          {scoreOptions.map((opt) => {
            const isActive = minScore === opt.value
            return (
              <button
                key={opt.value}
                onClick={() => setMinScore(opt.value)}
                className="px-2.5 py-1 rounded-md text-[11px] font-medium transition-all"
                style={{
                  backgroundColor: isActive ? theme.colors.navActive : 'transparent',
                  color: isActive ? theme.colors.text : theme.colors.textSub,
                }}
              >
                {opt.label}
              </button>
            )
          })}
        </div>
      </div>

      <SignalList
        signals={signals}
        isLoading={isLoading}
        isError={isError}
        error={error}
        emptyMessage={
          assetType === 'CRYPTO' ? t.signals.noCrypto
          : assetType === 'EQUITY' ? t.signals.noEquity
          : undefined
        }
      />
    </div>
  )
}
