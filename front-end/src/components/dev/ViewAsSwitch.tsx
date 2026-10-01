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

/** Dev switch: preview the app as Free / Premium / Owner. Only rendered
 *  when GET /auth/me says dev_tools (owner + DEV_TOOLS_ENABLED on the
 *  back-end). Nothing is written to the database.
 *  - rail: an eye button at the bottom of the desktop nav rail; the level
 *    menu opens beside it (never over the page content).
 *  - inline: three buttons, for the phone's More sheet. */
export function ViewAsSwitch({ variant }: { variant: 'rail' | 'inline' }) {
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

  const options = LEVELS.map((level) => {
    const active = level === current
    return (
      <button key={level} type="button" onClick={() => pick(level)} aria-pressed={active}
        className={`min-h-[40px] px-3 rounded-xl text-[14px] font-medium focus-visible:outline focus-visible:outline-2 ${variant === 'rail' ? 'min-w-[150px] text-left' : ''}`}
        style={{
          backgroundColor: active ? c.primary + '1f' : 'transparent',
          color: active ? c.primary : c.text,
          outlineColor: c.primary,
        }}>
        {tv.levels[level]}
      </button>
    )
  })

  if (variant === 'inline') {
    return (
      <div role="group" aria-label={tv.title} className="inline-flex items-center gap-1 rounded-xl p-1"
        style={{ backgroundColor: c.surfaceAlt, border: `1px dashed ${viewAs ? c.warning : c.border}` }}>
        <Eye size={14} aria-hidden="true" className="mx-1.5" style={{ color: viewAs ? c.warning : c.textSub }} />
        {options}
      </div>
    )
  }

  return (
    <div className="relative">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}
        aria-label={`${tv.title}: ${tv.levels[current]}`} title={`${tv.title}: ${tv.levels[current]}`}
        className="flex items-center justify-center w-10 h-10 rounded-xl focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        style={{
          backgroundColor: viewAs ? c.warning : 'transparent',
          color: viewAs ? c.bg : c.textSub,
          border: `1px dashed ${viewAs ? c.warning : c.border}`,
          outlineColor: c.primary,
        }}>
        {open ? <X size={16} aria-hidden="true" /> : <Eye size={16} aria-hidden="true" />}
      </button>
      {open && (
        <div role="group" aria-label={tv.title}
          className="absolute left-full ml-3 bottom-0 rounded-2xl p-2 flex flex-col gap-1 shadow-lg z-[70]"
          style={{ backgroundColor: c.surface, border: `1px solid ${c.border}` }}>
          <p className="px-2 pt-1 pb-0.5 text-[11px] font-semibold uppercase tracking-wide" style={{ color: c.textSub }}>{tv.title}</p>
          {options}
          <p className="px-2 pb-1 text-[11px] max-w-[190px]" style={{ color: c.textHint }}>{tv.note}</p>
        </div>
      )}
    </div>
  )
}
