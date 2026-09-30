'use client'

import { useCallback, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Plus, RefreshCw, Wallet } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useToast } from '@/hooks/useToast'
import { holdingsApi } from '@/lib/api'
import { etTime, fill, shortDate } from '@/lib/insights'
import { HOLDINGS_KEY, toHoldingsError, useHoldings, useHoldingsReview } from '@/hooks/useHoldings'
import { ImportPanel } from '@/components/holdings/ImportPanel'
import { AddHoldingForm } from '@/components/holdings/AddHoldingForm'
import { HoldingsList } from '@/components/holdings/HoldingsList'
import { AllocatePanel, ReviewPanel, TotalsCard } from '@/components/holdings/SidePanels'
import { errorText } from '@/components/holdings/format'
import { Skeleton } from '@/components/ui/Skeleton'
import { useAccess } from '@/hooks/useAccess'

export default function HoldingsPage() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const th = t.holdings
  const toast = useToast()
  const qc = useQueryClient()
  const q = useHoldings()
  const { can, slots } = useAccess()
  const canEdit = can('action.holdings.edit')
  const review = useHoldingsReview(can('action.holdings.review'))
  // How to add: one stock via search (default) or a pasted list / CSV.
  const [addOpen, setAddOpen] = useState(false)
  const [addMode, setAddMode] = useState<'search' | 'paste'>('search')
  const [refreshing, setRefreshing] = useState(false)

  const data = q.data
  const items = useMemo(() => data?.items ?? [], [data])
  const reviewedCount = useMemo(() => items.filter((h) => h.last_review).length, [items])
  const lastUpdated = useMemo(
    () => items.map((h) => h.status_updated_at).filter(Boolean).sort().pop() ?? null,
    [items],
  )
  const reviewingId = useMemo(() => {
    const j = review.job
    if (!j || j.status !== 'running' || !j.current) return null
    return items.find((h) => h.symbol === j.current)?.id ?? null
  }, [review.job, items])

  const onReview = useCallback((id: string) => { review.start({ ids: [id] }) }, [review])
  const onReviewAll = useCallback(() => { review.start({ all: true }) }, [review])

  const refresh = async () => {
    setRefreshing(true)
    try {
      await holdingsApi.refresh()
      toast.show(th.list.refreshing, 'info')
      setTimeout(() => qc.invalidateQueries({ queryKey: HOLDINGS_KEY }), 1500)
    } catch (e) {
      toast.show(errorText(toHoldingsError(e).code, th), 'error')
    } finally {
      setRefreshing(false)
    }
  }

  const loadError = q.error ? toHoldingsError(q.error) : null
  const empty = !!data && items.length === 0
  const showAdd = canEdit && (empty || addOpen)
  const closeAdd = () => { setAddOpen(false); setAddMode('search') }
  const monitorRunning = !!data?.monitor_running

  return (
    <div className="space-y-5 pb-4 min-w-0">
      <header className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between min-w-0">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold flex items-center gap-2" style={{ color: theme.colors.text }}>
            <Wallet size={22} aria-hidden="true" style={{ color: theme.colors.primary }} />
            {th.title}
          </h1>
          <p className="text-[13px] md:text-sm mt-1 max-w-2xl" style={{ color: theme.colors.textSub }}>{th.subtitle}</p>
          <p className="text-[12px] mt-1" style={{ color: theme.colors.textHint }}>{th.paperNote}</p>
          {slots && slots.limit !== null && (
            <p className="text-[12px] mt-1 tabular-nums" style={{ color: theme.colors.textSub }}>
              {fill(t.access.slots, { used: slots.used, limit: slots.limit })}
            </p>
          )}
        </div>
        {data && items.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {canEdit && <button type="button" onClick={() => { setAddOpen((o) => !o); setAddMode('search') }} aria-expanded={addOpen}
              className="min-h-[44px] px-4 rounded-xl text-[14px] font-semibold flex items-center gap-2 focus-visible:outline focus-visible:outline-2"
              style={{ backgroundColor: theme.colors.primary, color: theme.colors.surface, outlineColor: theme.colors.primary }}>
              <Plus size={16} aria-hidden="true" />{th.import.addMore}
            </button>}
            {can('action.holdings.refresh') && <button type="button" onClick={refresh} disabled={refreshing || monitorRunning}
              className="min-h-[44px] px-4 rounded-xl text-[14px] font-medium flex items-center gap-2 disabled:opacity-60 focus-visible:outline focus-visible:outline-2"
              style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.text, outlineColor: theme.colors.primary }}>
              <RefreshCw size={16} aria-hidden="true" className={monitorRunning ? 'animate-spin' : undefined} />
              {monitorRunning ? th.list.refreshing : th.list.refresh}
            </button>}
          </div>
        )}
      </header>

      {q.isLoading && (
        <div className="space-y-3" aria-busy="true">
          <Skeleton height={112} width="100%" />
          <Skeleton height={112} width="100%" />
        </div>
      )}

      {loadError && (
        <div role="alert" className="rounded-2xl p-4 text-[14px]"
          style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.down}`, color: theme.colors.text }}>
          {errorText(loadError.code, th)}
        </div>
      )}

      {empty && (
        <section className="rounded-2xl p-5" aria-labelledby="holdings-empty"
          style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.border}` }}>
          <h2 id="holdings-empty" className="text-[17px] font-semibold" style={{ color: theme.colors.text }}>{th.empty.title}</h2>
          <p className="text-[13px] mt-1" style={{ color: theme.colors.textSub }}>{th.empty.body}</p>
        </section>
      )}

      {data && showAdd && addMode === 'search' && (
        <AddHoldingForm existing={items} onDone={closeAdd} onCancel={empty ? undefined : closeAdd}
          onPasteList={() => setAddMode('paste')} />
      )}
      {data && showAdd && addMode === 'paste' && (
        <div className="flex flex-col gap-2">
          <button type="button" onClick={() => setAddMode('search')}
            className="self-start min-h-[44px] px-3 rounded-lg text-[13px] font-medium focus-visible:outline focus-visible:outline-2"
            style={{ color: theme.colors.primary, outlineColor: theme.colors.primary }}>
            {th.add.searchInstead}
          </button>
          <ImportPanel showCancel onCancel={() => setAddMode('search')} onDone={closeAdd} />
        </div>
      )}

      {data && items.length > 0 && (
        <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_340px] gap-5 items-start min-w-0">
          <section aria-labelledby="holdings-list" className="flex flex-col gap-3 min-w-0">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 id="holdings-list" className="text-[17px] font-semibold" style={{ color: theme.colors.text }}>
                {th.list.title} <span className="text-[13px] font-normal" style={{ color: theme.colors.textSub }}>{fill(th.list.count, { n: items.length })}</span>
              </h2>
              <p className="text-[12px]" style={{ color: theme.colors.textSub }} aria-live="polite">
                {monitorRunning ? th.list.refreshing
                  : lastUpdated ? fill(th.list.updated, { time: `${shortDate(lastUpdated, locale)} ${etTime(lastUpdated, locale)}` })
                    : th.list.neverUpdated}
              </p>
            </div>
            <HoldingsList items={items} maxWeight={data.settings.max_weight_pct} reviewingId={reviewingId}
              reviewBusy={review.running} onReview={onReview} />
            <p className="text-[12px]" style={{ color: theme.colors.textHint }}>{th.disclaimer}</p>
          </section>
          <aside className="flex flex-col gap-5 min-w-0 order-first xl:order-none">
            <TotalsCard data={data} />
            {can('action.holdings.review') && (
              <ReviewPanel data={data} job={review.job} running={review.running} error={review.error} onReviewAll={onReviewAll} />
            )}
            {can('action.holdings.allocate') && (
              <AllocatePanel hasHoldings={items.length > 0} reviewedCount={reviewedCount} />
            )}
          </aside>
        </div>
      )}
    </div>
  )
}
