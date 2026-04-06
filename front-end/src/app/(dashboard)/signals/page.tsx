'use client'

import { useState, useEffect, useCallback, useMemo } from 'react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useQueryClient } from '@tanstack/react-query'
import { useAllSignals } from '@/hooks/useSignals'
import { scansApi, type ScanProgress } from '@/lib/api'
import { SignalList } from '@/components/signals/SignalList'
import { Button } from '@/components/ui/Button'
import { ProgressBar } from '@/components/ui/ProgressBar'
import { useToast } from '@/hooks/useToast'
import { Search } from 'lucide-react'
import { Sidebar } from '@/components/layout/Sidebar'
import type { Signal, SignalFilters } from '@/types/signal'

export default function SignalsPage() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const toast = useToast()
  const queryClient = useQueryClient()
  const [bucket, setBucket] = useState<string>('All')
  const [assetType, setAssetType] = useState<string>('All')
  const [signalStyle, setSignalStyle] = useState<string>('All')
  const [actionFilter, setActionFilter] = useState<string>('All')
  const [minScore, setMinScore] = useState<number>(0)
  const [sortBy, setSortBy] = useState<'score' | 'rr' | 'change'>('score')
  const [search, setSearch] = useState<string>('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [scanId, setScanId] = useState<string | null>(null)
  const [progress, setProgress] = useState<ScanProgress | null>(null)
  const scanning = !!scanId

  // Debounce search input
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search), 300)
    return () => clearTimeout(timer)
  }, [search])

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
            t.signals.scanComplete.replace('{signals}', String(p.signals_found)).replace('{gems}', String(p.gems_found)),
            'success',
            5000,
          )
          setScanId(null)
          setProgress(null)
          queryClient.invalidateQueries({ queryKey: ['signals'] })
          queryClient.invalidateQueries({ queryKey: ['scans'] })
          queryClient.invalidateQueries({ queryKey: ['stats'] })
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

  const handleScanNow = useCallback(async () => {
    if (scanning) return
    try {
      const res = await scansApi.trigger('MORNING')
      setScanId(res.scan_id)
      toast.show(t.signals.scanStarted, 'info', 3000)
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

  // Client-side filters (asset type + signal style + action + search)
  const filtered = useMemo(() => {
    if (!allSignals) return undefined
    return allSignals.filter((s: Signal) => {
      if (assetType !== 'All' && s.asset_type !== assetType) return false
      if (signalStyle !== 'All' && s.signal_style !== signalStyle) return false
      if (actionFilter !== 'All' && s.action !== actionFilter) return false
      if (debouncedSearch && !s.symbol.toLowerCase().startsWith(debouncedSearch.toLowerCase())) return false
      return true
    })
  }, [allSignals, assetType, signalStyle, actionFilter, debouncedSearch])

  // Sorting
  const signals = useMemo(() => {
    if (!filtered) return undefined
    const sorted = [...filtered]
    if (sortBy === 'score') {
      sorted.sort((a, b) => b.score - a.score)
    } else if (sortBy === 'rr') {
      sorted.sort((a, b) => (b.risk_reward ?? 0) - (a.risk_reward ?? 0))
    } else if (sortBy === 'change') {
      sorted.sort((a, b) => Math.abs(b.change_pct ?? 0) - Math.abs(a.change_pct ?? 0))
    }
    return sorted
  }, [filtered, sortBy])

  // Summary stats
  const { buys, holds, avoids, marketRegime } = useMemo(() => ({
    buys: signals?.filter((s) => s.action === 'BUY').length ?? 0,
    holds: signals?.filter((s) => s.action === 'HOLD').length ?? 0,
    avoids: signals?.filter((s) => s.action === 'AVOID').length ?? 0,
    marketRegime: signals?.[0]?.market_regime ?? null,
  }), [signals])

  // Top pick = highest score in current filtered list
  const topPickId = useMemo(() => {
    if (!signals?.length) return undefined
    return signals.reduce((best, s) => (s.score > best.score ? s : best), signals[0]).id
  }, [signals])

  // Last scan time (latest created_at)
  const lastScanTime = useMemo(() => {
    if (!allSignals?.length) return null
    const latest = allSignals.reduce((newest, s) =>
      s.created_at > newest.created_at ? s : newest, allSignals[0])
    return latest.created_at
  }, [allSignals])

  const locale = useI18nStore((s) => s.locale)

  const formatRelativeTime = (isoDate: string): string => {
    const now = new Date()
    const date = new Date(isoDate)
    const diffMs = now.getTime() - date.getTime()
    const diffMin = Math.floor(diffMs / 60000)
    if (diffMin < 1) return t.signals.minAgo.replace('{n}', '1')
    if (diffMin < 60) return t.signals.minAgo.replace('{n}', String(diffMin))
    const diffHrs = Math.floor(diffMin / 60)
    if (diffHrs < 12) return t.signals.hoursAgo.replace('{n}', String(diffHrs))
    const timeStr = date.toLocaleTimeString(locale === 'pt' ? 'pt-BR' : 'en-US', { hour: 'numeric', minute: '2-digit' })
    return t.signals.todayAt.replace('{time}', timeStr)
  }

  const assetOptions = ['All', 'EQUITY', 'CRYPTO']
  const styleOptions = ['All', 'MOMENTUM', 'CONTRARIAN']
  const bucketOptions = ['All', 'SAFE_INCOME', 'HIGH_RISK']
  const actionOptions = ['All', 'BUY', 'HOLD', 'AVOID', 'SELL']
  const scoreOptions = [
    { label: t.signals.anyScore, value: 0 },
    { label: '60+', value: 60 },
    { label: '70+', value: 70 },
    { label: '80+', value: 80 },
  ]
  const sortOptions: { label: string; value: 'score' | 'rr' | 'change' }[] = [
    { label: t.signals.sortScore, value: 'score' },
    { label: t.signals.sortRR, value: 'rr' },
    { label: t.signals.sortChange, value: 'change' },
  ]

  const phaseLabel = (phase: string) => {
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

      {/* Content + Sidebar grid */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_300px] gap-6 items-start">
        <div className="space-y-5">

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
              {progress.gems_found > 0
                ? t.signals.signalsFoundGems.replace('{count}', String(progress.signals_found)).replace('{gems}', String(progress.gems_found))
                : t.signals.signalsFound.replace('{count}', String(progress.signals_found))}
            </p>
          )}
        </div>
      )}

      {/* Summary stats bar */}
      {signals && !scanning && signals.length > 0 && (
        <div
          className="flex items-center gap-4 rounded-xl px-4 py-2.5 text-[12px] font-medium"
          style={{ backgroundColor: theme.colors.surfaceAlt, border: `1px solid ${theme.colors.border}` }}
        >
          <div className="flex items-center gap-2">
            <span style={{ color: theme.colors.up }}>{buys} {t.signals.buy}</span>
            <span style={{ color: theme.colors.textHint }}>·</span>
            <span style={{ color: theme.colors.warning }}>{holds} {t.signals.hold}</span>
            <span style={{ color: theme.colors.textHint }}>·</span>
            <span style={{ color: theme.colors.down }}>{avoids} {t.signals.avoid}</span>
          </div>
          {marketRegime && (
            <span
              className="px-2 py-0.5 rounded-md text-[10px] font-bold"
              style={{
                backgroundColor:
                  marketRegime === 'CRISIS' ? theme.colors.down + '18'
                  : marketRegime === 'VOLATILE' ? theme.colors.warning + '18'
                  : theme.colors.up + '18',
                color:
                  marketRegime === 'CRISIS' ? theme.colors.down
                  : marketRegime === 'VOLATILE' ? theme.colors.warning
                  : theme.colors.up,
              }}
            >
              {marketRegime === 'CRISIS' ? t.signals.crisis : marketRegime === 'VOLATILE' ? t.signals.volatile : t.signals.trending}
            </span>
          )}
          {lastScanTime && (
            <span className="ml-auto" style={{ color: theme.colors.textSub }}>
              {t.signals.lastScan}: {formatRelativeTime(lastScanTime)}
            </span>
          )}
        </div>
      )}

      {/* Filter bar */}
      <div className="flex flex-wrap gap-2 items-center">
        {/* Search */}
        <div
          className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1"
          style={{ backgroundColor: theme.colors.nav }}
        >
          <Search size={12} style={{ color: theme.colors.textHint }} />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t.signals.searchPlaceholder}
            aria-label="Search signals"
            className="bg-transparent outline-none text-[11px] font-medium w-24"
            style={{ color: theme.colors.text }}
          />
        </div>

        {/* Asset type */}
        <div role="group" aria-label="Filter by asset type" className="inline-flex items-center gap-0.5 rounded-lg px-0.5 py-0.5" style={{ backgroundColor: theme.colors.nav }}>
          {assetOptions.map((opt) => {
            const isActive = assetType === opt
            return (
              <button
                key={opt}
                onClick={() => setAssetType(opt)}
                aria-pressed={isActive}
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

        {/* Signal Style */}
        <div role="group" aria-label="Filter by signal style" className="inline-flex items-center gap-0.5 rounded-lg px-0.5 py-0.5" style={{ backgroundColor: theme.colors.nav }}>
          {styleOptions.map((opt) => {
            const isActive = signalStyle === opt
            return (
              <button
                key={opt}
                onClick={() => setSignalStyle(opt)}
                aria-pressed={isActive}
                className="px-2.5 py-1 rounded-md text-[11px] font-medium transition-all"
                style={{
                  backgroundColor: isActive ? theme.colors.navActive : 'transparent',
                  color: isActive ? theme.colors.text : theme.colors.textSub,
                }}
              >
                {opt === 'MOMENTUM' ? t.signals.momentum : opt === 'CONTRARIAN' ? t.signals.contrarian : t.signals.all}
              </button>
            )
          })}
        </div>

        {/* Bucket */}
        <div role="group" aria-label="Filter by bucket" className="inline-flex items-center gap-0.5 rounded-lg px-0.5 py-0.5" style={{ backgroundColor: theme.colors.nav }}>
          {bucketOptions.map((opt) => {
            const isActive = bucket === opt
            return (
              <button
                key={opt}
                onClick={() => setBucket(opt)}
                aria-pressed={isActive}
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

        {/* Action */}
        <div role="group" aria-label="Filter by action" className="inline-flex items-center gap-0.5 rounded-lg px-0.5 py-0.5" style={{ backgroundColor: theme.colors.nav }}>
          {actionOptions.map((opt) => {
            const isActive = actionFilter === opt
            return (
              <button
                key={opt}
                onClick={() => setActionFilter(opt)}
                aria-pressed={isActive}
                className="px-2.5 py-1 rounded-md text-[11px] font-medium transition-all"
                style={{
                  backgroundColor: isActive ? theme.colors.navActive : 'transparent',
                  color: isActive ? theme.colors.text : theme.colors.textSub,
                }}
              >
                {opt === 'BUY' ? t.signals.buy : opt === 'HOLD' ? t.signals.hold : opt === 'AVOID' ? t.signals.avoid : opt === 'SELL' ? t.signals.sell : t.signals.all}
              </button>
            )
          })}
        </div>

        {/* Score */}
        <div role="group" aria-label="Filter by minimum score" className="inline-flex items-center gap-0.5 rounded-lg px-0.5 py-0.5" style={{ backgroundColor: theme.colors.nav }}>
          {scoreOptions.map((opt) => {
            const isActive = minScore === opt.value
            return (
              <button
                key={opt.value}
                onClick={() => setMinScore(opt.value)}
                aria-pressed={isActive}
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

        {/* Sort */}
        <div role="group" aria-label="Sort signals" className="inline-flex items-center gap-0.5 rounded-lg px-0.5 py-0.5" style={{ backgroundColor: theme.colors.nav }}>
          {sortOptions.map((opt) => {
            const isActive = sortBy === opt.value
            return (
              <button
                key={opt.value}
                onClick={() => setSortBy(opt.value)}
                aria-pressed={isActive}
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
        topPickId={topPickId}
        emptyMessage={
          assetType === 'CRYPTO' ? t.signals.noCrypto
          : assetType === 'EQUITY' ? t.signals.noEquity
          : undefined
        }
      />
        </div>
        <div className="sticky top-6 hidden lg:block">
          <Sidebar />
        </div>
      </div>
    </div>
  )
}
