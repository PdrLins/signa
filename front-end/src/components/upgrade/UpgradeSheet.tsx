'use client'

import { useEffect, useId, useRef, useState } from 'react'
import Link from 'next/link'
import { Bell, CandlestickChart, Check, Clock, Landmark, ListPlus, Sparkles, X, type LucideIcon } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useOverlayStore } from '@/store/overlayStore'
import { useAccess } from '@/hooks/useAccess'
import { fill } from '@/lib/insights'

const PERKS: [key: 'stocks' | 'alerts' | 'prices' | 'charts' | 'tax', icon: LucideIcon][] = [
  ['stocks', ListPlus], ['alerts', Bell], ['prices', Clock], ['charts', CandlestickChart], ['tax', Landmark],
]

/** The upgrade moment: one sheet (bottom sheet on phones, dialog on larger
 *  screens) opened from anywhere via useLimitHandler / overlayStore when an
 *  action hits the free plan's limit (403 slot_limit / alert_limit).
 *  Mounted once in the dashboard layout. There is no payment yet: the
 *  primary button says Premium is coming soon, inline. */
export function UpgradeSheet() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const tu = t.upgrade
  const state = useOverlayStore((s) => s.upgrade)
  const close = useOverlayStore((s) => s.closeUpgrade)
  const { slots } = useAccess()
  const titleId = useId()
  const bodyId = useId()
  const [soon, setSoon] = useState(false)
  const panelRef = useRef<HTMLDivElement>(null)
  const returnFocus = useRef<HTMLElement | null>(null)

  const open = !!state
  useEffect(() => {
    if (!open) return
    setSoon(false)
    returnFocus.current = document.activeElement as HTMLElement | null
    const first = panelRef.current?.querySelector<HTMLElement>('button, a[href]')
    first?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.preventDefault(); close() }
      if (e.key === 'Tab' && panelRef.current) {   // keep focus inside the dialog
        const els = Array.from(panelRef.current.querySelectorAll<HTMLElement>('button, a[href]'))
        if (!els.length) return
        const [a, b] = [els[0], els[els.length - 1]]
        if (e.shiftKey && document.activeElement === a) { e.preventDefault(); b.focus() }
        else if (!e.shiftKey && document.activeElement === b) { e.preventDefault(); a.focus() }
      }
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      returnFocus.current?.focus?.()
    }
  }, [open, close])

  if (!state) return null
  const limit = state.limit ?? (state.reason === 'slot_limit' ? slots?.limit ?? null : null)
  const title = fill(state.reason === 'slot_limit' ? tu.slotTitle : tu.alertTitle, { limit: limit ?? '' })
  const btnBase = 'min-h-[44px] px-4 rounded-xl text-[15px] w-full inline-flex items-center justify-center gap-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2'

  return (
    <div className="fixed inset-0 z-[80] flex items-end md:items-center justify-center" role="presentation">
      <div className="absolute inset-0" aria-hidden="true" onClick={close}
        style={{ backgroundColor: `${theme.colors.bg}D9` }} />
      <div ref={panelRef} role="dialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={bodyId}
        className="relative w-full md:max-w-[440px] rounded-t-3xl md:rounded-3xl p-5 pb-8 md:pb-5 flex flex-col gap-4 max-h-[90vh] overflow-y-auto"
        style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.border}` }}>
        <div className="flex items-start justify-between gap-3">
          <span className="w-11 h-11 rounded-2xl inline-flex items-center justify-center shrink-0" aria-hidden="true"
            style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.primary }}>
            <Sparkles size={22} />
          </span>
          <button type="button" onClick={close} aria-label={tu.close}
            className="min-h-[44px] min-w-[44px] rounded-full inline-flex items-center justify-center focus-visible:outline focus-visible:outline-2"
            style={{ color: theme.colors.textSub, outlineColor: theme.colors.primary }}>
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        <div className="flex flex-col gap-1">
          <h2 id={titleId} className="text-[20px] font-bold leading-snug" style={{ color: theme.colors.text }}>{title}</h2>
          <p id={bodyId} className="text-[14px]" style={{ color: theme.colors.textSub }}>{tu.body}</p>
        </div>
        <ul className="flex flex-col gap-2.5">
          {PERKS.map(([key, Icon]) => (
            <li key={key} className="flex items-center gap-3 text-[14px]" style={{ color: theme.colors.text }}>
              <span className="w-8 h-8 rounded-full inline-flex items-center justify-center shrink-0" aria-hidden="true"
                style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.primary }}>
                <Icon size={15} />
              </span>
              {tu.perks[key]}
            </li>
          ))}
        </ul>
        <div className="flex flex-col gap-2 pt-1">
          <button type="button" onClick={() => setSoon(true)} aria-describedby={soon ? `${titleId}-soon` : undefined}
            className={`${btnBase} font-semibold`}
            style={{ backgroundColor: theme.colors.primary, color: theme.colors.surface, outlineColor: theme.colors.primary }}>
            <Sparkles size={16} aria-hidden="true" />{tu.cta}
          </button>
          {soon && (
            <p id={`${titleId}-soon`} role="status" className="text-[13px] flex items-start gap-2 rounded-xl p-3"
              style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.text }}>
              <Check size={16} aria-hidden="true" className="shrink-0 mt-px" style={{ color: theme.colors.up }} />
              {tu.soon}
            </p>
          )}
          <Link href="/pricing" onClick={close}
            className="min-h-[44px] inline-flex items-center justify-center text-[13px] font-medium rounded-xl focus-visible:outline focus-visible:outline-2"
            style={{ color: theme.colors.primary, outlineColor: theme.colors.primary }}>
            {t.pricing.seePlans}
          </Link>
          {state.reason === 'slot_limit' ? (
            <Link href="/watchlist" onClick={close} className={`${btnBase} font-medium`}
              style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.text, outlineColor: theme.colors.primary }}>
              {tu.manage}
            </Link>
          ) : (
            <button type="button" onClick={close} className={`${btnBase} font-medium`}
              style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.text, outlineColor: theme.colors.primary }}>
              {tu.notNow}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
