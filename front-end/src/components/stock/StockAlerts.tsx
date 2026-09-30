'use client'

import { memo, useId, useState } from 'react'
import { BellRing, Sparkles, Trash2 } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useToast } from '@/hooks/useToast'
import { useAccess } from '@/hooks/useAccess'
import { useLimitHandler } from '@/hooks/useLimitHandler'
import { useAlerts, useCreateAlert, useDeleteAlert } from '@/hooks/useAlerts'
import { useOverlayStore } from '@/store/overlayStore'
import { DASH, fill, nativePrice, shortDate, signedPct } from '@/lib/insights'
import { isMigrationRequired, parseAmount, trackerErrorCode } from '@/lib/trackerErrors'
import { toHoldingsError } from '@/hooks/useHoldings'
import { Panel } from '@/components/insights/Panel'
import { Segmented, useButtonStyles, useFieldStyle } from '@/components/profile/ui'
import type { AlertDirection, PriceAlert } from '@/types/alerts'

const AlertRow = memo(function AlertRow({ a, onDelete, deleting, canEdit }: {
  a: PriceAlert
  onDelete: (id: string) => void
  deleting: boolean
  canEdit: boolean
}) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const ta = t.stock.alerts
  const dir = a.direction === 'above' ? ta.above : ta.below
  const price = nativePrice(a.target_price, a.symbol, a.currency)
  const d = a.distance_pct
  return (
    <li className="flex items-center gap-3 py-2.5 min-w-0" style={{ borderTop: `1px solid ${theme.colors.border}` }}>
      <span className="w-9 h-9 rounded-full inline-flex items-center justify-center shrink-0" aria-hidden="true"
        style={{ backgroundColor: theme.colors.surfaceAlt, color: a.active ? theme.colors.primary : theme.colors.textHint }}>
        <BellRing size={16} />
      </span>
      <div className="flex-1 min-w-0">
        <p className="text-[14px] font-medium tabular-nums" style={{ color: a.active ? theme.colors.text : theme.colors.textSub }}>
          {dir} {price}
        </p>
        {a.active ? (
          <p className="text-[12.5px] tabular-nums" style={{ color: theme.colors.textSub }}
            aria-label={d === null ? undefined : fill(ta.distanceAria, { pct: signedPct(d, 1) })}>
            {d === null ? DASH : fill(ta.distance, { pct: signedPct(d, 1) })}
          </p>
        ) : a.triggered_at ? (
          <p className="text-[12.5px] tabular-nums" style={{ color: theme.colors.warning }}>
            {fill(ta.triggered, { date: shortDate(a.triggered_at, locale), price: nativePrice(a.last_price, a.symbol, a.currency) })}
          </p>
        ) : (
          <p className="text-[12.5px]" style={{ color: theme.colors.textHint }}>{ta.off}</p>
        )}
      </div>
      {canEdit && (
        <button type="button" onClick={() => onDelete(a.id)} disabled={deleting}
          aria-label={fill(ta.deleteAria, { dir, price })}
          className="min-h-[44px] min-w-[44px] rounded-lg inline-flex items-center justify-center shrink-0 disabled:opacity-50 focus-visible:outline focus-visible:outline-2"
          style={{ color: theme.colors.textSub, outlineColor: theme.colors.primary }}>
          <Trash2 size={16} aria-hidden="true" />
        </button>
      )}
    </li>
  )
})

/** "Your alerts" on the stock page: the user's price alerts for this symbol
 *  with the distance from the current price, an add form (above / below +
 *  price) and delete. At the free limit the form becomes an upgrade prompt;
 *  a 403 alert_limit opens the upgrade sheet. */
export function StockAlerts({ symbol, currency, price }: { symbol: string; currency: string; price: number | null }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const ta = t.stock.alerts
  const toast = useToast()
  const { can } = useAccess()
  const canEdit = can('action.alerts.edit')
  const handleLimit = useLimitHandler()
  const openUpgrade = useOverlayStore((s) => s.openUpgrade)
  const q = useAlerts(symbol)
  const create = useCreateAlert()
  const del = useDeleteAlert()
  const f = useFieldStyle()
  const btn = useButtonStyles()
  const priceId = useId()
  const errId = useId()
  const [direction, setDirection] = useState<AlertDirection>('below')
  const [target, setTarget] = useState('')
  const [error, setError] = useState<string | null>(null)

  const data = q.data
  const items = data?.items ?? []
  const atLimit = !!data && data.limit !== null && data.remaining === 0

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const v = parseAmount(target)
    if (v === null || !Number.isFinite(v) || v <= 0) { setError(ta.invalidPrice); return }
    setError(null)
    create.mutate({ symbol, direction, target_price: v, currency }, {
      onSuccess: () => { setTarget(''); toast.show(fill(ta.created, { symbol }), 'success') },
      onError: (err) => {
        if (handleLimit(err)) return
        const he = toHoldingsError(err)
        if (he.code === 'already_crossed') {
          const cur = Number(he.extra?.current_price)
          setError(fill(ta.alreadyCrossed, { price: nativePrice(Number.isFinite(cur) ? cur : price, symbol, currency) }))
        } else if (he.code === 'invalid_price') setError(ta.invalidPrice)
        else if (he.code === 'migration_required') setError(ta.unavailable)
        else setError(ta.failed)
      },
    })
  }
  const onDelete = (id: string) => del.mutate(id, {
    onSuccess: () => toast.show(ta.deleted, 'info'),
    onError: () => toast.show(ta.failed, 'error'),
  })

  const migration = isMigrationRequired(q.error)
  const loadFailed = !!q.error && !migration && trackerErrorCode(q.error) !== 'upgrade_required'

  return (
    <Panel title={ta.title} subtitle={ta.subtitle}>
      <div className="flex flex-col gap-3 min-w-0">
        {migration && <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{ta.unavailable}</p>}
        {loadFailed && <p role="alert" className="text-[13px]" style={{ color: theme.colors.down }}>{ta.failed}</p>}
        {q.isLoading && <div className="h-12 rounded-xl animate-pulse" style={{ backgroundColor: theme.colors.surfaceAlt }} />}
        {data && (items.length === 0
          ? <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{ta.empty}</p>
          : <ul className="flex flex-col" aria-label={ta.title}>
              {items.map((a) => <AlertRow key={a.id} a={a} onDelete={onDelete} deleting={del.isPending} canEdit={canEdit} />)}
            </ul>)}

        {data && canEdit && !atLimit && (
          <form onSubmit={submit} className="flex flex-col gap-2" aria-label={ta.save} noValidate>
            <div className="flex flex-col gap-1">
              <span className="text-[12px]" style={{ color: theme.colors.textSub }}>{ta.direction}</span>
              <Segmented<AlertDirection> label={ta.direction} value={direction} onChange={setDirection}
                options={[{ value: 'above', label: ta.above }, { value: 'below', label: ta.below }]} />
            </div>
            <div className="flex flex-col sm:flex-row gap-2 sm:items-end">
              <label htmlFor={priceId} className={`${f.label} sm:max-w-[220px] flex-1`} style={{ color: f.labelColor }}>
                {fill(ta.price, { ccy: currency })}
                <input id={priceId} inputMode="decimal" value={target} onChange={(e) => { setTarget(e.target.value); setError(null) }}
                  placeholder={price !== null ? String(price) : ''} aria-invalid={!!error || undefined}
                  aria-describedby={error ? errId : undefined} className={f.input} style={f.style} />
              </label>
              <button type="submit" disabled={create.isPending || !target.trim()} className={btn.primary.className} style={btn.primary.style}>
                {create.isPending ? ta.saving : ta.save}
              </button>
            </div>
            {error && <p id={errId} role="alert" className="text-[13px]" style={{ color: theme.colors.down }}>{error}</p>}
          </form>
        )}

        {data && canEdit && atLimit && (
          <div className="rounded-xl p-3 flex flex-col sm:flex-row sm:items-center gap-2 justify-between"
            style={{ backgroundColor: theme.colors.surfaceAlt }}>
            <p className="text-[13px]" style={{ color: theme.colors.text }}>
              {fill(ta.limitNote, { active: data.active, limit: data.limit })}
            </p>
            <button type="button" onClick={() => openUpgrade('alert_limit', data.limit)}
              className={btn.primary.className} style={btn.primary.style}>
              <Sparkles size={15} aria-hidden="true" />{t.upgrade.cta}
            </button>
          </div>
        )}
        {data && data.limit !== null && !atLimit && data.active > 0 && (
          <p className="text-[12px] tabular-nums" style={{ color: theme.colors.textHint }}>
            {fill(ta.limitNote, { active: data.active, limit: data.limit })}
          </p>
        )}
        <p className="text-[12px]" style={{ color: theme.colors.textHint }}>{ta.deliveryNote}</p>
      </div>
    </Panel>
  )
}
