'use client'

import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Eye, X } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useMe } from '@/hooks/useAccess'
import { useViewAsStore } from '@/store/viewAsStore'
import type { AccessLevel } from '@/types/access'

const LEVELS: AccessLevel[] = ['free', 'premium', 'owner']

/** Floating dev switch: preview the app as Free / Premium / Owner.
 *  Only rendered when GET /auth/me says dev_tools (owner + DEV_TOOLS_ENABLED
 *  on the back-end). Nothing is written to the database. */
export function ViewAsSwitch() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const tv = t.devTools
  const qc = useQueryClient()
  const { data: me } = useMe()
  const viewAs = useViewAsStore((s) => s.viewAs)
  const setViewAs = useViewAsStore((s) => s.setViewAs)
  const [open, setOpen] = useState(false)

  if (!me?.dev_tools) return null
  const current: AccessLevel = me.access_level
  const c = theme.colors

  const pick = (level: AccessLevel) => {
    setViewAs(level === 'owner' ? null : level)
    setOpen(false)
    qc.invalidateQueries()
  }

  return (
    <div className="fixed left-3 bottom-24 md:bottom-4 md:left-24 z-[70] flex flex-col items-start gap-2">
      {open && (
        <div role="group" aria-label={tv.title}
          className="rounded-2xl p-2 flex flex-col gap-1 shadow-lg"
          style={{ backgroundColor: c.surface, border: `1px solid ${c.border}` }}>
          <p className="px-2 pt-1 pb-0.5 text-[11px] font-semibold uppercase tracking-wide" style={{ color: c.textSub }}>{tv.title}</p>
          {LEVELS.map((level) => {
            const active = level === current
            return (
              <button key={level} type="button" onClick={() => pick(level)} aria-pressed={active}
                className="min-h-[40px] min-w-[150px] px-3 rounded-xl text-left text-[14px] font-medium focus-visible:outline focus-visible:outline-2"
                style={{
                  backgroundColor: active ? c.primary + '1f' : 'transparent',
                  color: active ? c.primary : c.text,
                  outlineColor: c.primary,
                }}>
                {tv.levels[level]}
              </button>
            )
          })}
          <p className="px-2 pb-1 text-[11px] max-w-[190px]" style={{ color: c.textHint }}>{tv.note}</p>
        </div>
      )}
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}
        aria-label={`${tv.title}: ${tv.levels[current]}`}
        className="min-h-[40px] px-3 rounded-full flex items-center gap-2 text-[13px] font-semibold shadow-lg focus-visible:outline focus-visible:outline-2"
        style={{
          backgroundColor: viewAs ? c.warning : c.surfaceAlt,
          color: viewAs ? c.bg : c.text,
          border: `1px solid ${c.border}`,
          outlineColor: c.primary,
        }}>
        {open ? <X size={14} aria-hidden="true" /> : <Eye size={14} aria-hidden="true" />}
        {tv.levels[current]}
      </button>
    </div>
  )
}
