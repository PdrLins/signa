'use client'

import { useId, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Search } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { checkHref } from '@/lib/check'
import type { CheckMode } from '@/types/check'

/** Compact "Check a stock" box (Today header). Navigates to
 *  /check?ticker=XYZ (short-term, the default) or ...&mode=long, which
 *  starts the check automatically. */
export function CheckSearchBox({ className = '' }: { className?: string }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const router = useRouter()
  const id = useId()
  const modeId = useId()
  const [value, setValue] = useState('')
  const [mode, setMode] = useState<CheckMode>('short')

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const v = value.trim().toUpperCase()
    if (!v) return
    router.push(checkHref(v, mode))
  }

  return (
    <form role="search" onSubmit={submit} className={`flex items-center gap-1.5 ${className}`} aria-label={t.check.todayLabel}>
      <label htmlFor={id} className="sr-only">{t.check.todayLabel}</label>
      <div
        className="flex items-center h-11 rounded-[10px] pl-3 pr-1 gap-2 focus-within:outline focus-within:outline-2 w-full"
        style={{ border: `1px solid ${theme.colors.border}`, backgroundColor: theme.colors.surface, outlineColor: theme.colors.primary }}
      >
        <Search size={16} aria-hidden="true" style={{ color: theme.colors.textSub }} className="shrink-0" />
        <input
          id={id}
          type="text"
          inputMode="text"
          autoCapitalize="characters"
          autoComplete="off"
          spellCheck={false}
          maxLength={20}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={t.check.todayPlaceholder}
          className="bg-transparent outline-none text-sm min-w-0 flex-1 md:w-28"
          style={{ color: theme.colors.text, fontFamily: 'var(--font-mono)' }}
        />
        <label htmlFor={modeId} className="sr-only">{t.check.todayMode}</label>
        <select
          id={modeId}
          value={mode}
          onChange={(e) => setMode(e.target.value === 'long' ? 'long' : 'short')}
          className="h-11 bg-transparent text-[12px] font-medium outline-none cursor-pointer shrink-0 focus-visible:outline focus-visible:outline-2 rounded"
          style={{ color: theme.colors.textSub, outlineColor: theme.colors.primary }}
        >
          <option value="short">{t.check.modeShort.short}</option>
          <option value="long">{t.check.modeShort.long}</option>
        </select>
        <button
          type="submit"
          disabled={!value.trim()}
          className="h-9 px-3 rounded-lg text-[13px] font-medium disabled:opacity-50 focus-visible:outline focus-visible:outline-2"
          style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.primary, outlineColor: theme.colors.primary }}
        >
          {t.check.todaySubmit}
        </button>
      </div>
    </form>
  )
}
