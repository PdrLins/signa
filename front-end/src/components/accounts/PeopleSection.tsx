'use client'

import { memo, useId, useState } from 'react'
import { Pencil, Plus, Trash2, UserRound } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useToast } from '@/hooks/useToast'
import { peopleApi } from '@/lib/api'
import { fill } from '@/lib/insights'
import { trackerErrorText } from '@/lib/trackerErrors'
import { useInvalidateAccounts } from '@/hooks/useAccounts'
import { SectionCard, useButtonStyles, useFieldStyle } from '@/components/profile/ui'
import type { Person } from '@/types/accounts'

function NameForm({ initial, busy, error, submitLabel, onSubmit, onCancel }: {
  initial?: string
  busy: boolean
  error: string | null
  submitLabel: string
  onSubmit: (name: string) => void
  onCancel: () => void
}) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const ta = t.accountsPage
  const f = useFieldStyle()
  const btn = useButtonStyles()
  const id = useId()
  const [name, setName] = useState(initial ?? '')
  return (
    <form className="flex flex-col gap-2" onSubmit={(e) => { e.preventDefault(); if (name.trim()) onSubmit(name.trim()) }}>
      <label htmlFor={id} className={f.label} style={{ color: f.labelColor }}>
        {ta.personName}
        <input id={id} value={name} maxLength={60} autoFocus placeholder={ta.personNamePlaceholder}
          onChange={(e) => setName(e.target.value)} className={f.input} style={f.style} />
      </label>
      {error && <p role="alert" className="text-[13px]" style={{ color: theme.colors.down }}>{error}</p>}
      <div className="flex flex-wrap gap-2">
        <button type="submit" disabled={busy || !name.trim()} className={btn.primary.className} style={btn.primary.style}>
          {busy ? t.tracker.saving : submitLabel}
        </button>
        <button type="button" onClick={onCancel} className={btn.secondary.className} style={btn.secondary.style}>{t.tracker.cancel}</button>
      </div>
    </form>
  )
}

const PersonRow = memo(function PersonRow({ person, canEdit }: { person: Person; canEdit: boolean }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const ta = t.accountsPage
  const toast = useToast()
  const invalidate = useInvalidateAccounts()
  const btn = useButtonStyles()
  const [mode, setMode] = useState<'view' | 'edit' | 'delete'>('view')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const rename = async (name: string) => {
    setBusy(true); setError(null)
    try {
      await peopleApi.update(person.id, { name })
      toast.show(ta.personUpdated, 'success', 2000)
      invalidate()
      setMode('view')
    } catch (e) {
      setError(trackerErrorText(e, t))
    } finally {
      setBusy(false)
    }
  }
  const remove = async () => {
    setBusy(true); setError(null)
    try {
      await peopleApi.remove(person.id)
      toast.show(ta.personDeleted, 'success', 2000)
      invalidate()
    } catch (e) {
      setError(trackerErrorText(e, t))
      setBusy(false)
    }
  }

  return (
    <li className="rounded-xl p-3 flex flex-col gap-2" style={{ backgroundColor: theme.colors.surfaceAlt }}>
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <UserRound size={16} aria-hidden="true" style={{ color: theme.colors.textSub }} />
          <span className="text-[14px] font-medium truncate" style={{ color: theme.colors.text }}>{person.name}</span>
          <span className="text-[12px]" style={{ color: theme.colors.textSub }}>{fill(ta.accountsCount, { n: person.accounts_count })}</span>
        </div>
        {canEdit && mode === 'view' && (
          <div className="flex gap-1 shrink-0">
            <button type="button" onClick={() => setMode('edit')} className={btn.icon.className} style={btn.icon.style}
              aria-label={fill(ta.editPerson, { name: person.name })}>
              <Pencil size={16} aria-hidden="true" />
            </button>
            <button type="button" onClick={() => setMode('delete')} className={btn.icon.className}
              style={{ ...btn.icon.style, color: theme.colors.down }} aria-label={fill(ta.deletePerson, { name: person.name })}>
              <Trash2 size={16} aria-hidden="true" />
            </button>
          </div>
        )}
      </div>
      {mode === 'edit' && (
        <NameForm initial={person.name} busy={busy} error={error} submitLabel={t.tracker.save}
          onSubmit={rename} onCancel={() => { setMode('view'); setError(null) }} />
      )}
      {mode === 'delete' && (
        <div role="alertdialog" aria-label={fill(ta.deletePerson, { name: person.name })} className="flex flex-col gap-2">
          <p className="text-[13px]" style={{ color: theme.colors.text }}>{fill(ta.personDeleteConfirm, { name: person.name })}</p>
          {error && <p role="alert" className="text-[13px]" style={{ color: theme.colors.down }}>{error}</p>}
          <div className="flex flex-wrap gap-2">
            <button type="button" disabled={busy} onClick={remove} className={btn.danger.className}
              style={{ ...btn.danger.style, border: `1px solid ${theme.colors.down}` }}>
              {busy ? t.tracker.deleting : t.tracker.delete}
            </button>
            <button type="button" onClick={() => { setMode('view'); setError(null) }} className={btn.secondary.className} style={btn.secondary.style}>
              {t.tracker.cancel}
            </button>
          </div>
        </div>
      )}
    </li>
  )
})

export function PeopleSection({ people, canEdit }: { people: Person[]; canEdit: boolean }) {
  const t = useI18nStore((s) => s.t)
  const ta = t.accountsPage
  const toast = useToast()
  const invalidate = useInvalidateAccounts()
  const btn = useButtonStyles()
  const [adding, setAdding] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const add = async (name: string) => {
    setBusy(true); setError(null)
    try {
      await peopleApi.create({ name })
      toast.show(ta.personCreated, 'success', 2000)
      invalidate()
      setAdding(false)
    } catch (e) {
      setError(trackerErrorText(e, t))
    } finally {
      setBusy(false)
    }
  }

  return (
    <SectionCard title={ta.people} subtitle={ta.peopleHelp}
      right={canEdit && !adding ? (
        <button type="button" onClick={() => setAdding(true)} className={btn.secondary.className} style={btn.secondary.style}>
          <Plus size={16} aria-hidden="true" />{ta.addPerson}
        </button>
      ) : undefined}>
      {adding && (
        <NameForm busy={busy} error={error} submitLabel={ta.addPerson} onSubmit={add}
          onCancel={() => { setAdding(false); setError(null) }} />
      )}
      {people.length > 0 && (
        <ul className="flex flex-col gap-2">
          {people.map((p) => <PersonRow key={p.id} person={p} canEdit={canEdit} />)}
        </ul>
      )}
    </SectionCard>
  )
}
