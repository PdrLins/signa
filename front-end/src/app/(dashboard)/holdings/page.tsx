'use client'

import { Suspense, useCallback, useMemo, useState } from 'react'
import Link from 'next/link'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { useQueryClient } from '@tanstack/react-query'
import { ArrowLeftRight, ChevronDown, ClipboardList, Landmark, Plus, RefreshCw, Search, Upload } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useToast } from '@/hooks/useToast'
import { holdingsApi } from '@/lib/api'
import { etTime, fill, shortDate } from '@/lib/insights'
import { HOLDINGS_KEY, toHoldingsError, useHoldings, useHoldingsReview } from '@/hooks/useHoldings'
import { ImportPanel } from '@/components/holdings/ImportPanel'
import { AddHoldingForm } from '@/components/holdings/AddHoldingForm'
import { HoldingsList } from '@/components/holdings/HoldingsList'
import { AllocatePanel, ReviewPanel } from '@/components/holdings/SidePanels'
import { errorText } from '@/components/holdings/format'
import { Skeleton } from '@/components/ui/Skeleton'
import { ActionMenu, type ActionMenuItem } from '@/components/ui/ActionMenu'
import { useAccess } from '@/hooks/useAccess'
import { useAccounts } from '@/hooks/useAccounts'
import { usePortfolioSummary, useScope } from '@/hooks/usePortfolioInsights'
import { PortfolioValueCard } from '@/components/tracker/PortfolioValueCard'
import { PerformanceTab } from '@/components/tracker/PerformanceTab'
import { AllocationTab } from '@/components/tracker/AllocationTab'
import { HideAmountsButton, QueryError, ScopeSelect, isUpgrade } from '@/components/tracker/ui'
import { isMigrationRequired } from '@/lib/trackerErrors'
import { SearchButton } from '@/components/search/GlobalSearch'
import { SegmentedTabs } from '@/components/ui/SegmentedTabs'

type Tab = 'list' | 'performance' | 'allocation'
const TABS: Tab[] = ['list', 'performance', 'allocation']

export default function HoldingsPage() {
  return (
    <Suspense fallback={null}>
      <HoldingsInner />
    </Suspense>
  )
}

/** Holdings: List (the positions, value chart on top) · Performance ·
 *  Allocation (formerly the Insights page; /insights redirects here). The
 *  tab and the account scope live in the URL. */
function HoldingsInner() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const th = t.holdings
  const params = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()
  const { scope, setScope, scoped } = useScope()
  const { can } = useAccess()
  const accountsQ = useAccounts()
  const accounts = useMemo(() => accountsQ.data?.items ?? [], [accountsQ.data])

  const canInsights = can('area.insights')
  const raw = params.get('tab')
  const tab: Tab = canInsights && (raw === 'performance' || raw === 'allocation') ? raw : 'list'
  const setTab = useCallback((next: Tab) => {
    const q = new URLSearchParams(params.toString())
    if (next === 'list') q.delete('tab')
    else q.set('tab', next)
    const s = q.toString()
    router.replace(s ? `${pathname}?${s}` : pathname, { scroll: false })
  }, [params, pathname, router])

  // The add form opens from the "+ Add" menu (or ?add=1 / ?add=paste).
  const [add, setAdd] = useState<null | 'search' | 'paste'>(
    params.get('add') === 'paste' ? 'paste' : params.get('add') === '1' ? 'search' : null)
  const tabOptions = useMemo(() => TABS.map((k) => ({ value: k, label: th.tabs[k] })), [th])

  return (
    <div className="space-y-4 pb-4 min-w-0">
      <header className="flex items-start justify-between gap-3 min-w-0">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold" style={{ color: theme.colors.text }}>{th.list.title}</h1>
          <p className="text-[13px] mt-0.5" style={{ color: theme.colors.textSub }}>{th.subtitleShort}</p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <SearchButton />
          <HideAmountsButton />
          <AddMenu onAdd={(mode) => { setAdd(mode); setTab('list') }} />
        </div>
      </header>

      <div className="flex flex-col sm:flex-row sm:items-center gap-3 min-w-0">
        {canInsights && <SegmentedTabs value={tab} options={tabOptions} onChange={setTab} label={th.tabs.label} idBase="holdings-tab" />}
        {accounts.length > 0 && (
          <div className="flex items-center gap-2 min-w-0 sm:ml-auto">
            <ScopeSelect scope={scope} onChange={setScope} />
            <Link href="/profile/accounts" aria-label={th.accounts.manage} title={th.accounts.manage}
              className="shrink-0 min-h-[44px] min-w-[44px] rounded-full inline-flex items-center justify-center focus-visible:outline focus-visible:outline-2"
              style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.textSub, outlineColor: theme.colors.primary }}>
              <Landmark size={16} aria-hidden="true" />
            </Link>
          </div>
        )}
      </div>

      <div role={canInsights ? 'tabpanel' : undefined} id="holdings-tab-panel"
        aria-labelledby={canInsights ? `holdings-tab-${tab}` : undefined} className="min-w-0">
        {tab === 'list' && <ListTab add={add} setAdd={setAdd} />}
        {tab === 'performance' && <PerformanceTab scope={scope} />}
        {tab === 'allocation' && <AllocationTab scope={scope} scoped={scoped} />}
      </div>
    </div>
  )
}

/** "+ Add" → add a stock, paste a list, record a trade, import a CSV, accounts. */
function AddMenu({ onAdd }: { onAdd: (mode: 'search' | 'paste') => void }) {
  const t = useI18nStore((s) => s.t)
  const ta = t.holdings.addMenu
  const { can } = useAccess()
  const toast = useToast()
  const qc = useQueryClient()
  const items: ActionMenuItem[] = [
    ...(can('action.holdings.edit') ? [
      { key: 'stock', label: ta.stock, icon: Search, onSelect: () => onAdd('search') },
      { key: 'paste', label: ta.paste, icon: ClipboardList, onSelect: () => onAdd('paste') },
    ] : []),
    ...(can('action.transactions.edit') ? [{ key: 'trade', label: ta.trade, icon: ArrowLeftRight, href: '/profile/transactions?add=1' }] : []),
    ...(can('action.import.csv') ? [{ key: 'csv', label: ta.csv, icon: Upload, href: '/profile/transactions?import=1' }] : []),
    ...(can('action.accounts.edit') ? [{ key: 'accounts', label: ta.accounts, icon: Landmark, href: '/profile/accounts' }] : []),
    ...(can('action.holdings.refresh') ? [{
      key: 'refresh', label: ta.refresh, icon: RefreshCw, onSelect: async () => {
        try {
          await holdingsApi.refresh()
          toast.show(t.holdings.list.refreshing, 'info')
          setTimeout(() => qc.invalidateQueries({ queryKey: HOLDINGS_KEY }), 1500)
        } catch (e) {
          toast.show(errorText(toHoldingsError(e).code, t.holdings), 'error')
        }
      },
    }] : []),
  ]
  return (
    <ActionMenu items={items} label={ta.label} variant="primary"
      trigger={<><Plus size={16} aria-hidden="true" /><span className="hidden sm:inline">{ta.button}</span><ChevronDown size={14} aria-hidden="true" className="hidden sm:inline" /></>} />
  )
}

function ListTab({ add, setAdd }: { add: null | 'search' | 'paste'; setAdd: (m: null | 'search' | 'paste') => void }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const th = t.holdings
  const { scope, scoped } = useScope()
  const accountId = scope.account_id ?? null
  const q = useHoldings(scope)
  const { can } = useAccess()
  const summary = usePortfolioSummary(scope, can('area.home'))
  const canEdit = can('action.holdings.edit')
  const review = useHoldingsReview(can('action.holdings.review'))

  const data = q.data
  const items = useMemo(() => data?.items ?? [], [data])
  const reviewedCount = useMemo(() => items.filter((h) => h.last_review).length, [items])
  const missingShares = useMemo(() => items.filter((h) => !h.shares).length, [items])
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

  const loadError = q.error ? toHoldingsError(q.error) : null
  const empty = !!data && items.length === 0 && !scoped
  const emptyInAccount = !!data && items.length === 0 && scoped
  const summaryError = summary.error && !summary.data && !isMigrationRequired(summary.error) && !isUpgrade(summary.error)
    ? summary.error : null
  const mode = canEdit && (add ?? (empty ? 'search' : null))
  const closeAdd = () => setAdd(null)
  const monitorRunning = !!data?.monitor_running
  const brainNotes = can('action.holdings.review') || can('action.holdings.allocate')

  return (
    <div className="flex flex-col gap-4 min-w-0">
      {summary.data && items.length > 0 && <PortfolioValueCard scope={scope} summary={summary.data} />}
      {summaryError && <QueryError error={summaryError} onRetry={() => summary.refetch()} />}

      {q.isLoading && (
        <div className="space-y-2" aria-busy="true">
          <Skeleton height={72} width="100%" />
          <Skeleton height={72} width="100%" />
          <Skeleton height={72} width="100%" />
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

      {data && mode === 'search' && (
        <AddHoldingForm existing={items} defaultAccountId={accountId ?? ''} onDone={closeAdd} onCancel={empty ? undefined : closeAdd}
          onPasteList={() => setAdd('paste')} />
      )}
      {data && mode === 'paste' && (
        <div className="flex flex-col gap-2">
          <button type="button" onClick={() => setAdd('search')}
            className="self-start min-h-[44px] px-3 rounded-lg text-[13px] font-medium focus-visible:outline focus-visible:outline-2"
            style={{ color: theme.colors.primary, outlineColor: theme.colors.primary }}>
            {th.add.searchInstead}
          </button>
          <ImportPanel defaultAccountId={accountId ?? ''} showCancel onCancel={() => setAdd(empty ? 'search' : null)} onDone={closeAdd} />
        </div>
      )}

      {emptyInAccount && !mode && (
        <p className="text-[14px] rounded-2xl p-4" role="status"
          style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.border}`, color: theme.colors.textSub }}>
          {th.accounts.noneInAccount}
        </p>
      )}

      {data && items.length > 0 && (
        <section aria-labelledby="holdings-list" className="flex flex-col gap-2 min-w-0">
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
            <h2 id="holdings-list" className="text-[15px] font-semibold" style={{ color: theme.colors.text }}>
              {fill(th.list.count, { n: items.length })}
            </h2>
            <p className="text-[12px]" style={{ color: theme.colors.textHint }} aria-live="polite">
              {monitorRunning ? th.list.refreshing
                : lastUpdated ? fill(th.list.updated, { time: `${shortDate(lastUpdated, locale)} ${etTime(lastUpdated, locale)}` })
                  : th.list.neverUpdated}
            </p>
          </div>
          <HoldingsList items={items} maxWeight={data.settings.max_weight_pct} reviewingId={reviewingId}
            reviewBusy={review.running} onReview={onReview} />
          {missingShares > 0 && (
            <p className="text-[12px]" style={{ color: theme.colors.textSub }}>{fill(th.list.missingShares, { n: missingShares })}</p>
          )}
          <p className="text-[12px]" style={{ color: theme.colors.textHint }}>{th.disclaimer}</p>
        </section>
      )}

      {data && items.length > 0 && brainNotes && (
        <details className="group rounded-2xl min-w-0" style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.border}` }}>
          <summary className="min-h-[52px] px-4 py-3 flex items-center justify-between gap-3 cursor-pointer list-none rounded-2xl focus-visible:outline focus-visible:outline-2"
            style={{ outlineColor: theme.colors.primary }}>
            <span className="min-w-0">
              <span className="block text-[15px] font-semibold" style={{ color: theme.colors.text }}>{th.brainNotes.title}</span>
              <span className="block text-[12px]" style={{ color: theme.colors.textSub }}>
                {fill(th.brainNotes.subtitle, { n: reviewedCount, total: items.length })}
              </span>
            </span>
            <ChevronDown size={18} aria-hidden="true" className="shrink-0 transition-transform group-open:rotate-180" style={{ color: theme.colors.textSub }} />
          </summary>
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 p-4 pt-0 items-start">
            {can('action.holdings.review') && (
              <ReviewPanel data={data} job={review.job} running={review.running} error={review.error} onReviewAll={onReviewAll} />
            )}
            {can('action.holdings.allocate') && (
              <AllocatePanel hasHoldings={items.length > 0} reviewedCount={reviewedCount} />
            )}
          </div>
        </details>
      )}
    </div>
  )
}
