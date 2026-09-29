'use client'

import { useCallback, useId, useMemo, useRef, useState } from 'react'
import { GitCompareArrows, Plus, X } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { SymbolCombobox, resolveRawEntry } from '@/components/check/SymbolCombobox'
import { COMPARE_MAX, COMPARE_MIN } from '@/lib/check'
import { fill } from '@/lib/insights'
import type { SymbolMatch } from '@/types/symbols'

/** 2–3 ticker inputs (symbol or company name, with suggestions) + Compare. */
export function CompareForm({ values, onChange, onSubmit, running, remaining }: {
  values: string[]
  onChange: (v: string[]) => void
  onSubmit: (tickers: string[]) => void
  running: boolean
  remaining?: number | null
}) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const tc = t.check.compare
  const baseId = useId()
  const helpId = useId()
  const [invalid, setInvalid] = useState(false)
  const suggestions = useRef<SymbolMatch[][]>([[], [], []])
  const onResults = useMemo(
    () => [0, 1, 2].map((i) => (r: SymbolMatch[]) => { suggestions.current[i] = r }),
    [],
  )

  const setAt = useCallback((i: number, v: string) => {
    const next = [...values]
    next[i] = v
    onChange(next)
    setInvalid(false)
  }, [values, onChange])

  const tickers = values.map((v, i) => resolveRawEntry(v, suggestions.current[i] ?? [])).filter(Boolean)
  const distinct = Array.from(new Set(tickers))
  const canSubmit = !running && distinct.length >= COMPARE_MIN

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    if (running) return
    if (distinct.length < COMPARE_MIN || distinct.length !== tickers.length) {
      setInvalid(true)
      return
    }
    onSubmit(distinct)
  }

  const inputStyle = {
    backgroundColor: theme.colors.surfaceAlt, color: theme.colors.text,
    border: `1px solid ${theme.colors.border}`, outlineColor: theme.colors.primary,
  }

  return (
    <form role="search" onSubmit={submit} className="flex flex-col gap-2" aria-label={tc.submit} noValidate>
      <div className="flex flex-col gap-2">
        {values.map((v, i) => {
          const id = `${baseId}-t${i}`
          return (
            <div key={i} className="flex flex-col gap-1">
              <label htmlFor={id} className="text-[13px] font-medium" style={{ color: theme.colors.text }}>
                {fill(tc.tickerLabel, { n: i + 1 })}
              </label>
              <div className="relative flex gap-2">
                <SymbolCombobox
                  id={id}
                  value={v}
                  onChange={(x) => setAt(i, x)}
                  onPick={(m) => setAt(i, m.symbol)}
                  onResults={onResults[i]}
                  placeholder={t.check.placeholder}
                  describedBy={helpId}
                  className="flex-1 min-w-0 h-11 rounded-[10px] px-3 text-[15px] outline-0 focus-visible:outline focus-visible:outline-2"
                  style={inputStyle}
                />
                {i >= COMPARE_MIN && (
                  <button
                    type="button"
                    onClick={() => onChange(values.filter((_, j) => j !== i))}
                    disabled={running}
                    aria-label={fill(tc.remove, { n: i + 1 })}
                    className="inline-flex items-center justify-center w-11 h-11 shrink-0 rounded-[10px] disabled:opacity-60 focus-visible:outline focus-visible:outline-2"
                    style={{ ...inputStyle, color: theme.colors.textSub }}
                  >
                    <X size={16} aria-hidden="true" />
                  </button>
                )}
              </div>
            </div>
          )
        })}
      </div>
      <div className="flex flex-wrap items-center gap-2 mt-1">
        {values.length < COMPARE_MAX && (
          <button
            type="button"
            onClick={() => onChange([...values, ''])}
            disabled={running}
            className="inline-flex items-center gap-1.5 min-h-11 px-3 rounded-[10px] text-[13px] font-medium disabled:opacity-60 focus-visible:outline focus-visible:outline-2"
            style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.primary, outlineColor: theme.colors.primary, border: `1px solid ${theme.colors.border}` }}
          >
            <Plus size={15} aria-hidden="true" />
            {tc.add}
          </button>
        )}
        <button
          type="submit"
          disabled={!canSubmit}
          className="inline-flex items-center justify-center gap-2 min-h-11 px-4 rounded-[10px] text-sm font-medium disabled:opacity-60 ml-auto focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          style={{ backgroundColor: theme.colors.primary, color: theme.colors.surface, outlineColor: theme.colors.primary }}
        >
          <GitCompareArrows size={16} aria-hidden="true" />
          {running ? tc.running : tc.submit}
        </button>
      </div>
      <p id={helpId} className="text-[12px]" style={{ color: invalid ? theme.colors.warning : theme.colors.textSub }} aria-live="polite">
        {invalid ? tc.needTwo : tc.help}
        {!invalid && remaining != null && <> · {fill(tc.remaining, { n: remaining })}</>}
      </p>
    </form>
  )
}
