'use client'

import { memo, useEffect, useId, useState } from 'react'
import { Smartphone } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useToast } from '@/hooks/useToast'
import { useNotificationPrefs, useUpdateNotificationPrefs } from '@/hooks/useProfile'
import { fill } from '@/lib/insights'
import { isMigrationRequired, parseAmount, trackerErrorText } from '@/lib/trackerErrors'
import {
  LoadError, MigrationNotice, SectionCard, ToggleRow, TrackerHeader, useButtonStyles, useFieldStyle,
} from '@/components/profile/ui'
import { Skeleton } from '@/components/ui/Skeleton'
import type { NotificationKey, NotificationPref, NotificationPrefsUpdate } from '@/types/profile'

const KEYS: NotificationKey[] = [
  'exdiv_reminder', 'dividend_paid', 'dividend_change', 'check_changed',
  'earnings', 'big_move', 'analyst_ratings', 'economy',
]

const PrefRow = memo(function PrefRow({ k, pref, onSave, busy }: {
  k: NotificationKey
  pref: NotificationPref
  onSave: (body: NotificationPrefsUpdate) => void
  busy: boolean
}) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const tn = t.notifications
  const f = useFieldStyle()
  const btn = useButtonStyles()
  const inputId = useId()
  const item = tn.items[k]
  const current = pref.threshold_pct ?? 5
  const [threshold, setThreshold] = useState(String(current))
  useEffect(() => { setThreshold(String(current)) }, [current])
  const parsed = parseAmount(threshold)
  const invalid = parsed === null || Number.isNaN(parsed) || parsed < 1 || parsed > 50
  return (
    <li className="py-2 flex flex-col gap-2" style={{ borderTop: `1px solid ${theme.colors.border}` }}>
      <ToggleRow label={item.title} desc={item.desc} checked={pref.enabled} disabled={busy}
        onChange={(v) => onSave({ [k]: { enabled: v } })} />
      {k === 'big_move' && pref.enabled && (
        <form className="flex flex-wrap items-end gap-2" aria-label={tn.threshold}
          onSubmit={(e) => { e.preventDefault(); if (!invalid && parsed !== current) onSave({ big_move: { threshold_pct: parsed as number } }) }}>
          <label htmlFor={inputId} className={`${f.label} w-32`} style={{ color: f.labelColor }}>
            {tn.threshold}
            <input id={inputId} inputMode="decimal" value={threshold} onChange={(e) => setThreshold(e.target.value)}
              aria-invalid={invalid || undefined} aria-describedby={`${inputId}-help`}
              className={`${f.input} tabular-nums`} style={{ ...f.style, borderColor: invalid ? theme.colors.down : theme.colors.border }} />
          </label>
          <button type="submit" disabled={invalid || busy || parsed === current} className={btn.secondary.className} style={btn.secondary.style}>
            {tn.saveThreshold}
          </button>
          <p id={`${inputId}-help`} className="w-full text-[12px]" style={{ color: invalid ? theme.colors.down : theme.colors.textHint }}>
            {invalid ? tn.thresholdInvalid : fill(tn.thresholdHelp, { pct: current })}
          </p>
        </form>
      )}
    </li>
  )
})

export default function NotificationsPage() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const tn = t.notifications
  const toast = useToast()
  const q = useNotificationPrefs()
  const update = useUpdateNotificationPrefs()

  const onSave = (body: NotificationPrefsUpdate) => {
    update.mutate(body, {
      onSuccess: () => toast.show(t.tracker.saved, 'success', 2000),
      onError: (e) => toast.show(trackerErrorText(e, t), 'error'),
    })
  }

  return (
    <div className="space-y-4 pb-4 min-w-0 max-w-3xl">
      <TrackerHeader title={tn.title} subtitle={tn.subtitle} backHref="/profile" backLabel={tn.back} />
      <p className="text-[13px] flex items-center gap-2 rounded-xl p-3" style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.border}`, color: theme.colors.textSub }}>
        <Smartphone size={16} aria-hidden="true" style={{ color: theme.colors.primary }} className="shrink-0" />{tn.phoneNote}
      </p>
      {q.isLoading && <Skeleton height={320} width="100%" />}
      {isMigrationRequired(q.error) && <MigrationNotice />}
      {!!q.error && !isMigrationRequired(q.error) && <LoadError message={trackerErrorText(q.error, t)} onRetry={() => q.refetch()} />}
      {q.data && (
        <SectionCard title={tn.title} subtitle={q.data.is_default ? tn.defaults : undefined}>
          <ul className="flex flex-col">
            {KEYS.map((k) => (
              <PrefRow key={k} k={k} pref={q.data.prefs[k] ?? { enabled: false }} onSave={onSave} busy={update.isPending} />
            ))}
          </ul>
        </SectionCard>
      )}
    </div>
  )
}
