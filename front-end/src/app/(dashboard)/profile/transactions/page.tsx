'use client'

import { Suspense, useEffect, useId, useMemo, useState } from 'react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { useQueryClient } from '@tanstack/react-query'
import { Plus, Upload } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useToast } from '@/hooks/useToast'
import { useAccess } from '@/hooks/useAccess'
import { useAccounts } from '@/hooks/useAccounts'
import { TRANSACTIONS_KEY, useTransactions } from '@/hooks/useTransactions'
import { transactionsApi } from '@/lib/api'
import { fill } from '@/lib/insights'
import { isMigrationRequired, trackerErrorText } from '@/lib/trackerErrors'
import {
  LoadError, MigrationNotice, SectionCard, TrackerHeader, useButtonStyles, useFieldStyle,
} from '@/components/profile/ui'
import { TransactionForm } from '@/components/transactions/TransactionForm'
import { TransactionItem } from '@/components/transactions/TransactionItem'
import { CsvImport } from '@/components/transactions/CsvImport'
import { Skeleton } from '@/components/ui/Skeleton'
import { TX_TYPES, type TransactionFilters, type TransactionInput, type TxType } from '@/types/transactions'
import type { Account } from '@/types/accounts'

const PAGE = 50
const NO_ACCOUNTS: Account[] = []

export default function TransactionsPage() {
  return (
    <Suspense fallback={null}>
      <TransactionsInner />
    </Suspense>
  )
}

function TransactionsInner() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const tt = t.transactionsPage
  const toast = useToast()
  const qc = useQueryClient()
  const params = useSearchParams()
  const { can } = useAccess()
  const canEdit = can('action.transactions.edit')
  const canImport = can('action.import.csv')
  const f = useFieldStyle()
  const btn = useButtonStyles()
  const ids = { acct: useId(), sym: useId(), type: useId() }

  const [accountId, setAccountId] = useState('')
  const [symbolInput, setSymbolInput] = useState('')
  const [symbol, setSymbol] = useState('')
  const [type, setType] = useState<TxType | ''>('')
  const [limit, setLimit] = useState(PAGE)
  const [adding, setAdding] = useState(params.get('add') === '1')
  const presetSymbol = (params.get('symbol') ?? '').toUpperCase()
  const [importOpen, setImportOpen] = useState(params.get('import') === '1')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // symbol filter: debounce typing
  useEffect(() => {
    const id = setTimeout(() => setSymbol(symbolInput.trim().toUpperCase()), 400)
    return () => clearTimeout(id)
  }, [symbolInput])
  useEffect(() => { setLimit(PAGE) }, [accountId, symbol, type])

  const filters = useMemo<TransactionFilters>(() => ({
    ...(accountId ? { account_id: accountId } : {}),
    ...(symbol ? { symbol } : {}),
    ...(type ? { type } : {}),
    limit,
  }), [accountId, symbol, type, limit])
  const q = useTransactions(filters)
  const accountsQ = useAccounts()
  const accounts = accountsQ.data?.items ?? NO_ACCOUNTS
  const items = useMemo(() => q.data?.items ?? [], [q.data])
  const filtered = !!(accountId || symbol || type)

  const create = async (body: TransactionInput) => {
    setBusy(true)
    setError(null)
    try {
      await transactionsApi.create(body)
      toast.show(tt.added, 'success', 2000)
      qc.invalidateQueries({ queryKey: TRANSACTIONS_KEY })
      qc.invalidateQueries({ queryKey: ['holdings'] })
      setAdding(false)
    } catch (e) {
      setError(trackerErrorText(e, t))
    } finally {
      setBusy(false)
    }
  }

  const migration = isMigrationRequired(q.error)

  return (
    <div className="space-y-4 pb-4 min-w-0 max-w-4xl">
      <TrackerHeader title={tt.title} subtitle={tt.subtitle} backHref="/profile" backLabel={tt.back}
        right={!migration ? (
          <div className="flex flex-wrap gap-2">
            {canEdit && !adding && (
              <button type="button" onClick={() => { setAdding(true); setError(null) }} className={btn.primary.className} style={btn.primary.style}>
                <Plus size={16} aria-hidden="true" />{tt.add}
              </button>
            )}
            {canImport && !importOpen && (
              <button type="button" onClick={() => setImportOpen(true)} className={btn.secondary.className} style={btn.secondary.style}>
                <Upload size={16} aria-hidden="true" />{tt.import.title}
              </button>
            )}
          </div>
        ) : undefined} />

      {migration && <MigrationNotice />}
      {!!q.error && !migration && <LoadError message={trackerErrorText(q.error, t)} onRetry={() => q.refetch()} />}

      {!migration && canImport && importOpen && <CsvImport onClose={() => setImportOpen(false)} />}

      {!migration && adding && (
        <SectionCard title={tt.addTitle}>
          {accountsQ.data && accounts.length === 0 && (
            <p className="text-[13px]" style={{ color: theme.colors.textSub }}>
              {tt.noAccounts}{' '}
              <Link href="/profile/accounts" className="underline font-medium focus-visible:outline focus-visible:outline-2"
                style={{ color: theme.colors.primary, outlineColor: theme.colors.primary }}>{tt.manageAccounts}</Link>
            </p>
          )}
          <TransactionForm accounts={accounts} defaultAccountId={accountId} defaultSymbol={presetSymbol} busy={busy} error={error} onSubmit={create}
            onCancel={() => { setAdding(false); setError(null) }} />
        </SectionCard>
      )}

      {!migration && (
        <SectionCard title={tt.title}
          right={q.data ? (
            <span className="text-[12px] tabular-nums" style={{ color: theme.colors.textSub }}>
              {fill(tt.count, { shown: items.length, total: q.data.total })}
            </span>
          ) : undefined}>
          <div role="group" aria-label={tt.filters} className="grid grid-cols-1 sm:grid-cols-3 gap-2">
            <label htmlFor={ids.acct} className={f.label} style={{ color: f.labelColor }}>
              {tt.account}
              <select id={ids.acct} value={accountId} onChange={(e) => setAccountId(e.target.value)} className={f.input} style={f.style}>
                <option value="">{tt.allAccounts}</option>
                {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
            </label>
            <label htmlFor={ids.sym} className={f.label} style={{ color: f.labelColor }}>
              {tt.symbol}
              <input id={ids.sym} value={symbolInput} maxLength={24} placeholder={tt.symbolPlaceholder} autoCapitalize="characters"
                autoCorrect="off" spellCheck={false} onChange={(e) => setSymbolInput(e.target.value)} className={`${f.input} font-mono`} style={f.style} />
            </label>
            <label htmlFor={ids.type} className={f.label} style={{ color: f.labelColor }}>
              {tt.type}
              <select id={ids.type} value={type} onChange={(e) => setType(e.target.value as TxType | '')} className={f.input} style={f.style}>
                <option value="">{tt.allTypes}</option>
                {TX_TYPES.map((ty) => <option key={ty} value={ty}>{tt.types[ty]}</option>)}
              </select>
            </label>
          </div>
          {filtered && (
            <button type="button" onClick={() => { setAccountId(''); setSymbolInput(''); setSymbol(''); setType('') }}
              className="self-start min-h-[44px] px-2 text-[13px] font-medium rounded-lg focus-visible:outline focus-visible:outline-2"
              style={{ color: theme.colors.primary, outlineColor: theme.colors.primary }}>
              {tt.clearFilters}
            </button>
          )}

          {q.isLoading && <Skeleton height={180} width="100%" />}
          {q.data && items.length === 0 && (
            <p className="text-[14px] py-4" role="status" style={{ color: theme.colors.textSub }}>{filtered ? tt.emptyFiltered : tt.empty}</p>
          )}
          {items.length > 0 && (
            <ul className="flex flex-col" aria-busy={q.isFetching || undefined}>
              {items.map((tx) => <TransactionItem key={tx.id} tx={tx} accounts={accounts} canEdit={canEdit} />)}
            </ul>
          )}
          {q.data?.has_more && limit < 500 && (
            <button type="button" onClick={() => setLimit((l) => Math.min(500, l + PAGE))} disabled={q.isFetching}
              className={`${btn.secondary.className} self-start`} style={btn.secondary.style}>
              {tt.loadMore}
            </button>
          )}
          <p className="text-[12px]" style={{ color: theme.colors.textHint }}>{t.tracker.notAdvice}</p>
        </SectionCard>
      )}
    </div>
  )
}
