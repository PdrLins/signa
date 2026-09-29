'use client'

import { useEffect, useId, useState, type CSSProperties, type KeyboardEvent } from 'react'
import { Loader2 } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useSymbolSearch } from '@/hooks/useSymbolSearch'
import { fill } from '@/lib/insights'
import type { SymbolMatch } from '@/types/symbols'

/** Pick what a raw (nothing highlighted) Enter should check: the typed text,
 *  or — when it is clearly a name ("royal bank") — the top suggestion. */
export function resolveRawEntry(raw: string, results: SymbolMatch[]): string {
  const v = raw.trim()
  if (/\s/.test(v) && results.length > 0) return results[0].symbol
  return v.toUpperCase()
}

interface SymbolComboboxProps {
  /** id of the <input> (for an external <label htmlFor>). */
  id: string
  value: string
  onChange: (v: string) => void
  /** A suggestion was chosen (click, tap, or Enter on the highlighted row). */
  onPick: (m: SymbolMatch) => void
  /** Latest suggestions, so a raw Enter can use them (see resolveRawEntry). */
  onResults?: (r: SymbolMatch[]) => void
  onFocusChange?: (focused: boolean) => void
  placeholder?: string
  describedBy?: string
  ariaLabel?: string
  className?: string
  style?: CSSProperties
  /** Class for the dropdown panel; it is absolutely positioned against the
   *  nearest `relative` ancestor, so the parent decides its width. */
  panelClassName?: string
}

/** Ticker / company-name search input with a suggestions listbox
 *  (WAI-ARIA combobox, list autocomplete). Enter on a highlighted option
 *  picks it; otherwise the surrounding <form> submits as usual. */
export function SymbolCombobox({
  id, value, onChange, onPick, onResults, onFocusChange, placeholder, describedBy, ariaLabel,
  className = '', style, panelClassName = 'left-0 right-0 top-full mt-1.5',
}: SymbolComboboxProps) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const ts = t.check.search
  const listId = useId()
  const statusId = useId()
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)

  const { results, settled, loading, isError, term } = useSymbolSearch(value, { enabled: open })
  const typed = value.trim()
  const showPanel = open && typed.length > 0
  const optId = (i: number) => `${listId}-opt-${i}`

  useEffect(() => { setActive(-1) }, [term])
  useEffect(() => { onResults?.(results) }, [results, onResults])
  useEffect(() => {
    if (active < 0) return
    document.getElementById(optId(active))?.scrollIntoView({ block: 'nearest' })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active])

  const close = () => { setOpen(false); setActive(-1) }
  const pick = (m: SymbolMatch) => { close(); onPick(m) }

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    const n = results.length
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault()
        if (!open) { setOpen(true); return }
        if (n) setActive((a) => (a + 1) % n)
        break
      case 'ArrowUp':
        e.preventDefault()
        if (!open) { setOpen(true); return }
        if (n) setActive((a) => (a <= 0 ? n - 1 : a - 1))
        break
      case 'Enter':
        if (showPanel && active >= 0 && results[active]) {
          e.preventDefault()
          pick(results[active])
        } else {
          close() // let the form submit the raw text
        }
        break
      case 'Escape':
        if (open) { e.preventDefault(); close() }
        break
      case 'Tab':
        close()
        break
    }
  }

  const empty = settled && results.length === 0
  const typeLabel = (m: SymbolMatch) => ts.types[m.type] ?? m.type

  return (
    <>
      <input
        id={id}
        type="text"
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={showPanel}
        aria-controls={listId}
        aria-activedescendant={showPanel && active >= 0 ? optId(active) : undefined}
        aria-describedby={describedBy}
        aria-label={ariaLabel}
        autoComplete="off"
        autoCapitalize="none"
        autoCorrect="off"
        spellCheck={false}
        enterKeyHint="search"
        maxLength={40}
        value={value}
        onChange={(e) => { onChange(e.target.value); setOpen(true) }}
        onKeyDown={onKeyDown}
        onFocus={() => onFocusChange?.(true)}
        onBlur={() => { close(); onFocusChange?.(false) }}
        placeholder={placeholder}
        className={className}
        style={style}
      />
      <span id={statusId} className="sr-only" aria-live="polite">
        {showPanel && settled ? (results.length ? fill(ts.count, { n: results.length }) : fill(ts.noMatches, { q: typed })) : ''}
      </span>
      <div
        hidden={!showPanel}
        className={`absolute z-40 rounded-[12px] overflow-hidden ${panelClassName}`}
        style={{
          backgroundColor: theme.colors.surface,
          border: `1px solid ${theme.colors.border}`,
          boxShadow: theme.isDark ? '0 12px 32px rgba(0,0,0,0.55)' : '0 12px 32px rgba(0,0,0,0.14)',
        }}
      >
        <ul
          id={listId}
          role="listbox"
          aria-label={ts.suggestions}
          className="max-h-[min(60vh,420px)] overflow-y-auto overscroll-contain py-1"
        >
          {results.map((m, i) => {
            const on = i === active
            return (
              <li
                key={m.symbol}
                id={optId(i)}
                role="option"
                aria-selected={on}
                onMouseDown={(e) => e.preventDefault()} // keep focus in the input
                onMouseMove={() => { if (!on) setActive(i) }}
                onClick={() => pick(m)}
                className="flex items-center gap-3 min-h-11 px-3 py-1.5 cursor-pointer select-none"
                style={{ backgroundColor: on ? theme.colors.surfaceAlt : 'transparent' }}
              >
                <span className="flex flex-col min-w-0 flex-1">
                  <span className="flex items-center gap-1.5 min-w-0">
                    <span className="text-[14px] font-semibold shrink-0" style={{ color: theme.colors.text, fontFamily: 'var(--font-mono)' }}>
                      {m.symbol}
                    </span>
                    {m.source === 'signa' && (
                      <span
                        className="w-1.5 h-1.5 rounded-full shrink-0"
                        style={{ backgroundColor: theme.colors.primary }}
                        title={ts.tracked}
                        aria-label={ts.tracked}
                      />
                    )}
                  </span>
                  {m.name && (
                    <span className="text-[12.5px] truncate" style={{ color: theme.colors.textSub }}>{m.name}</span>
                  )}
                </span>
                <span className="flex items-center gap-1.5 shrink-0">
                  <span className="text-[11.5px]" style={{ color: theme.colors.textSub }}>{m.exchange_label}</span>
                  <span
                    className="text-[10.5px] font-medium px-1.5 py-px rounded"
                    style={{ color: theme.colors.textSub, border: `1px solid ${theme.colors.border}`, backgroundColor: theme.colors.surfaceAlt }}
                  >
                    {typeLabel(m)}
                  </span>
                </span>
              </li>
            )
          })}
        </ul>
        {results.length === 0 && (
          <div className="px-3 py-3 text-[13px]" style={{ color: theme.colors.textSub }}>
            {loading ? (
              <span className="flex items-center gap-2">
                <Loader2 size={14} aria-hidden="true" className="animate-spin" />
                {ts.searching}
              </span>
            ) : isError ? (
              ts.failed
            ) : empty ? (
              <span className="flex flex-col gap-0.5">
                <span style={{ color: theme.colors.text }}>{fill(ts.noMatches, { q: typed })}</span>
                <span>{ts.noMatchesHint}</span>
              </span>
            ) : null}
          </div>
        )}
      </div>
    </>
  )
}
