'use client'

import { useAccess } from '@/hooks/useAccess'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useOverlayStore } from '@/store/overlayStore'
import { fill } from '@/lib/insights'

/** "8 of 10 stocks" + a thin bar (GET /auth/me slots). Hidden when the
 *  plan is unlimited. At the limit it becomes a button that opens the
 *  upgrade sheet. */
export function SlotMeter({ className = '' }: { className?: string }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const { slots } = useAccess()
  const openUpgrade = useOverlayStore((s) => s.openUpgrade)
  if (!slots || slots.limit === null || slots.limit <= 0) return null
  const { used, limit } = slots
  const full = used >= limit
  const pct = Math.min(100, (used / limit) * 100)
  const color = full ? theme.colors.warning : pct >= 80 ? theme.colors.warning : theme.colors.primary
  const aria = fill(t.access.slotMeterAria, { used, limit })

  const body = (
    <>
      <span className="flex items-center justify-between gap-2 text-[12.5px] tabular-nums">
        <span style={{ color: theme.colors.text }} className="font-medium">{fill(t.access.slotMeter, { used, limit })}</span>
        {full && <span className="font-semibold" style={{ color: theme.colors.warning }}>{t.access.slotMeterFull}</span>}
      </span>
      <span className="block h-1.5 rounded-full overflow-hidden" style={{ backgroundColor: theme.colors.surfaceAlt }}>
        <span className="block h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: color }} />
      </span>
    </>
  )
  const cls = `flex flex-col gap-1.5 w-full max-w-[260px] ${className}`
  if (full) {
    return (
      <button type="button" onClick={() => openUpgrade('slot_limit', limit)} aria-label={`${aria}. ${t.upgrade.cta}`}
        className={`${cls} text-left min-h-[44px] justify-center rounded-lg focus-visible:outline focus-visible:outline-2`}
        style={{ outlineColor: theme.colors.primary }}>
        {body}
      </button>
    )
  }
  return (
    <div className={cls} role="meter" aria-valuemin={0} aria-valuemax={limit} aria-valuenow={used} aria-label={aria}>
      {body}
    </div>
  )
}
