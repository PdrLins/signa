'use client'

import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { Panel } from '@/components/insights/Panel'
import type { ScorecardItem } from '@/types/check'
import { scorecardReason, useRatingColor } from './format'

/** One card per category with a rating chip and a one-line reason. */
export function ScorecardGrid({ items }: { items: ScorecardItem[] }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const tl = t.check.long
  const color = useRatingColor()

  return (
    <Panel title={tl.scorecardTitle} subtitle={tl.scorecardSubtitle}>
      <ul className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-2.5">
        {items.map((s) => {
          const c = color(s.rating)
          const label = (tl.categories as Record<string, string>)[s.key] ?? s.key
          const rating = (tl.ratings as Record<string, string>)[s.rating] ?? s.rating
          return (
            <li
              key={s.key}
              className="rounded-[10px] p-3 flex flex-col gap-1.5 min-w-0"
              style={{ backgroundColor: theme.colors.surfaceAlt, borderLeft: `3px solid ${c}` }}
            >
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-[13px] font-semibold" style={{ color: theme.colors.text }}>{label}</h3>
                <span
                  className="text-[11px] font-semibold px-2 py-0.5 rounded-full shrink-0"
                  style={{ color: c, border: `1px solid ${c}` }}
                >
                  <span className="sr-only">{label}: </span>{rating}
                </span>
              </div>
              <p className="text-[12.5px] leading-snug break-words" style={{ color: theme.colors.textSub }}>{scorecardReason(s, t)}</p>
            </li>
          )
        })}
      </ul>
    </Panel>
  )
}
