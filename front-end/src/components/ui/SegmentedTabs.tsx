'use client'

import { useRef } from 'react'
import { useTheme } from '@/hooks/useTheme'

/** A segmented tab bar (role=tablist) for switching sections of one page.
 *  Arrow keys move between tabs. The panel uses id `${idBase}-panel` and is
 *  labelled by `${idBase}-${value}`. Scrolls sideways when it doesn't fit. */
export function SegmentedTabs<V extends string>({ value, options, onChange, label, idBase }: {
  value: V
  options: { value: V; label: string }[]
  onChange: (v: V) => void
  label: string
  idBase: string
}) {
  const theme = useTheme()
  const c = theme.colors
  const ref = useRef<HTMLDivElement>(null)
  const move = (dir: 1 | -1) => {
    const i = options.findIndex((o) => o.value === value)
    const next = options[(i + dir + options.length) % options.length]
    onChange(next.value)
    requestAnimationFrame(() => ref.current?.querySelector<HTMLElement>(`#${idBase}-${next.value}`)?.focus())
  }
  return (
    <div ref={ref} role="tablist" aria-label={label}
      className="inline-flex max-w-full overflow-x-auto rounded-xl p-1 gap-1 shrink-0"
      style={{ backgroundColor: c.surfaceAlt }}>
      {options.map((o) => {
        const on = o.value === value
        return (
          <button key={o.value} type="button" role="tab" id={`${idBase}-${o.value}`} aria-selected={on}
            aria-controls={`${idBase}-panel`} tabIndex={on ? 0 : -1}
            onClick={() => onChange(o.value)}
            onKeyDown={(e) => {
              if (e.key === 'ArrowRight') { e.preventDefault(); move(1) }
              if (e.key === 'ArrowLeft') { e.preventDefault(); move(-1) }
            }}
            className="min-h-[40px] px-4 rounded-lg text-[14px] whitespace-nowrap focus-visible:outline focus-visible:outline-2"
            style={{
              backgroundColor: on ? c.surface : 'transparent',
              color: on ? c.text : c.textSub,
              fontWeight: on ? 600 : 500,
              boxShadow: on ? '0 1px 3px rgba(0,0,0,0.18)' : 'none',
              outlineColor: c.primary,
            }}>
            {o.label}
          </button>
        )
      })}
    </div>
  )
}
