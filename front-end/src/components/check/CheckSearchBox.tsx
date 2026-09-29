'use client'

import { useCallback, useId, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Search } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { checkHref } from '@/lib/check'
import { SymbolCombobox, resolveRawEntry } from '@/components/check/SymbolCombobox'
import type { CheckMode } from '@/types/check'
import type { SymbolMatch } from '@/types/symbols'

const MODES: CheckMode[] = ['short', 'long']

/** `#rrggbb` + alpha -> rgba(); other formats are returned unchanged. */
function tint(color: string, alpha: number): string {
  const m = /^#([0-9a-f]{6})$/i.exec(color)
  if (!m) return color
  const n = parseInt(m[1], 16)
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`
}

/** Small "Trade | Hold" segmented toggle (two real buttons, aria-pressed). */
export function ModeToggle({ mode, onChange, label }: { mode: CheckMode; onChange: (m: CheckMode) => void; label: string }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  return (
    <div
      role="group"
      aria-label={label}
      className="inline-flex items-center gap-0.5 p-0.5 rounded-[9px] shrink-0"
      style={{ backgroundColor: theme.colors.surfaceAlt, border: `1px solid ${theme.colors.border}` }}
    >
      {MODES.map((m) => {
        const on = mode === m
        return (
          <button
            key={m}
            type="button"
            aria-pressed={on}
            onClick={() => onChange(m)}
            className="min-h-11 sm:min-h-9 px-3 rounded-[7px] text-[12.5px] font-medium outline-0 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 transition-colors"
            style={{
              backgroundColor: on ? theme.colors.surface : 'transparent',
              color: on ? theme.colors.text : theme.colors.textSub,
              boxShadow: on ? (theme.isDark ? '0 1px 3px rgba(0,0,0,0.45)' : '0 1px 3px rgba(0,0,0,0.10)') : undefined,
              outlineColor: theme.colors.textSub,
            }}
          >
            {t.check.modeShort[m]}
          </button>
        )
      })}
    </div>
  )
}

/** Today's "Check a stock" box: a full-width search (symbol or company
 *  name, with suggestions) + Trade/Hold toggle. Navigates to
 *  /check?ticker=XYZ&mode=…, which starts the check automatically. */
export function CheckSearchBox({ className = '' }: { className?: string }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const router = useRouter()
  const id = useId()
  const [value, setValue] = useState('')
  const [mode, setMode] = useState<CheckMode>('short')
  const [focused, setFocused] = useState(false)
  const results = useRef<SymbolMatch[]>([])
  const onResults = useCallback((r: SymbolMatch[]) => { results.current = r }, [])

  const go = (symbol: string) => {
    if (!symbol) return
    router.push(checkHref(symbol.toUpperCase(), mode))
  }

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    go(resolveRawEntry(value, results.current))
  }

  return (
    <form role="search" onSubmit={submit} className={`relative w-full ${className}`} aria-label={t.check.todayLabel}>
      <label htmlFor={id} className="sr-only">{t.check.todayLabel}</label>
      <div
        className="flex flex-col sm:flex-row sm:items-center gap-2 rounded-[14px] p-1.5 sm:pl-3.5 transition-[box-shadow,border-color,padding] duration-150"
        style={{
          border: `1px solid ${focused ? tint(theme.colors.primary, 0.55) : theme.colors.border}`,
          backgroundColor: theme.colors.surface,
          boxShadow: focused
            ? `0 0 0 4px ${tint(theme.colors.primary, 0.16)}, 0 6px 20px ${theme.isDark ? 'rgba(0,0,0,0.35)' : 'rgba(0,0,0,0.06)'}`
            : 'none',
        }}
      >
        <div className={`flex items-center gap-2.5 flex-1 min-w-0 pl-2 sm:pl-0 transition-[min-height] duration-150 ${focused ? 'min-h-[52px]' : 'min-h-11'}`}>
          <Search size={focused ? 18 : 16} aria-hidden="true" style={{ color: focused ? theme.colors.text : theme.colors.textSub }} className="shrink-0" />
          <SymbolCombobox
            id={id}
            value={value}
            onChange={setValue}
            onPick={(m) => go(m.symbol)}
            onResults={onResults}
            onFocusChange={setFocused}
            placeholder={t.check.todayPlaceholder}
            className={`bg-transparent outline-0 min-w-0 flex-1 h-11 transition-[font-size] duration-150 ${focused ? 'text-[16px]' : 'text-[15px]'}`}
            style={{ color: theme.colors.text }}
            panelClassName="left-0 right-0 top-full mt-2"
          />
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <ModeToggle mode={mode} onChange={setMode} label={t.check.todayMode} />
          <button
            type="submit"
            disabled={!value.trim()}
            className="flex-1 sm:flex-none min-h-11 sm:min-h-10 px-4 rounded-[10px] text-[13px] font-semibold disabled:opacity-50 outline-0 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
            style={{ backgroundColor: theme.colors.primary, color: theme.colors.surface, outlineColor: theme.colors.primary }}
          >
            {t.check.todaySubmit}
          </button>
        </div>
      </div>
    </form>
  )
}
