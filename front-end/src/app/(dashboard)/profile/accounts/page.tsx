'use client'

import { useMemo, useState } from 'react'
import { Landmark, Plus } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useToast } from '@/hooks/useToast'
import { useAccess } from '@/hooks/useAccess'
import { useAccounts, useInvalidateAccounts, usePeople } from '@/hooks/useAccounts'
import { useProfile, useProfileOptions } from '@/hooks/useProfile'
import { accountsApi } from '@/lib/api'
import { isMigrationRequired, trackerErrorText } from '@/lib/trackerErrors'
import {
  LoadError, MigrationNotice, SectionCard, TrackerHeader, useButtonStyles,
} from '@/components/profile/ui'
import { AccountForm } from '@/components/accounts/AccountForm'
import { AccountRow } from '@/components/accounts/AccountRow'
import { PeopleSection } from '@/components/accounts/PeopleSection'
import { Skeleton } from '@/components/ui/Skeleton'
import type { Account, AccountInput } from '@/types/accounts'

const NO_ACCOUNTS: Account[] = []

export default function AccountsPage() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const ta = t.accountsPage
  const toast = useToast()
  const { can } = useAccess()
  const canEdit = can('action.accounts.edit')
  const accountsQ = useAccounts()
  const peopleQ = usePeople()
  const profile = useProfile(can('area.profile'))
  const options = useProfileOptions(can('area.profile'))
  const invalidate = useInvalidateAccounts()
  const btn = useButtonStyles()
  const [adding, setAdding] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const accounts = accountsQ.data?.items ?? NO_ACCOUNTS
  const people = useMemo(() => peopleQ.data?.items ?? [], [peopleQ.data])
  const types = useMemo(() => accountsQ.data?.account_types.types ?? [], [accountsQ.data])
  const typeLocked = !can('action.accounts.type')
  const currencies = useMemo(() => options.data?.currencies ?? [], [options.data])
  const homeCurrency = profile.data?.home_currency ?? 'CAD'
  const othersById = useMemo(
    () => new Map(accounts.map((a) => [a.id, accounts.filter((o) => o.id !== a.id)])),
    [accounts],
  )

  const create = async (body: AccountInput) => {
    setBusy(true)
    setError(null)
    try {
      await accountsApi.create(body)
      toast.show(ta.created, 'success', 2000)
      invalidate()
      setAdding(false)
    } catch (e) {
      setError(trackerErrorText(e, t))
    } finally {
      setBusy(false)
    }
  }

  const migration = isMigrationRequired(accountsQ.error)
  const empty = !!accountsQ.data && accounts.length === 0
  const showForm = canEdit && (adding || empty)

  return (
    <div className="space-y-4 pb-4 min-w-0 max-w-3xl">
      <TrackerHeader title={ta.title} subtitle={ta.subtitle} backHref="/profile" backLabel={ta.back} />
      {accountsQ.isLoading && <Skeleton height={200} width="100%" />}
      {migration && <MigrationNotice />}
      {!!accountsQ.error && !migration && <LoadError message={trackerErrorText(accountsQ.error, t)} onRetry={() => accountsQ.refetch()} />}

      {accountsQ.data && (
        <SectionCard title={ta.accounts}
          right={canEdit && !showForm ? (
            <button type="button" onClick={() => { setAdding(true); setError(null) }} className={btn.primary.className} style={btn.primary.style}>
              <Plus size={16} aria-hidden="true" />{ta.addAccount}
            </button>
          ) : undefined}>
          {empty && (
            <p className="text-[14px] flex items-center gap-2" style={{ color: theme.colors.text }}>
              <Landmark size={18} aria-hidden="true" style={{ color: theme.colors.primary }} />{ta.empty}
            </p>
          )}
          {showForm && (
            <AccountForm people={people} currencies={currencies} homeCurrency={homeCurrency} types={types}
              typeLocked={typeLocked} busy={busy} error={error} onSubmit={create}
              onCancel={empty ? undefined : () => { setAdding(false); setError(null) }} />
          )}
          {accounts.length > 0 && (
            <ul className="flex flex-col gap-2">
              {accounts.map((a) => (
                <AccountRow key={a.id} account={a} others={othersById.get(a.id) ?? NO_ACCOUNTS} people={people}
                  currencies={currencies} homeCurrency={homeCurrency} types={types} typeLocked={typeLocked} canEdit={canEdit} />
              ))}
            </ul>
          )}
        </SectionCard>
      )}

      {accountsQ.data && peopleQ.data && <PeopleSection people={people} canEdit={canEdit} />}
    </div>
  )
}
