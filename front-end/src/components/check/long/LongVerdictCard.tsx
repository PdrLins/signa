'use client'

import { forwardRef } from 'react'
import { RefreshCw } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { mono } from '@/components/insights/Panel'
import { etTime, fill, nativePrice, shortDate } from '@/lib/insights'
import type { LongCheckResult } from '@/types/check'
import { longText, useLongVerdictStyle } from './format'

/** Verdict + the AI's summary, strengths / concerns / what to watch / DCA note. */
export const LongVerdictCard = forwardRef<HTMLHeadingElement, {
  result: LongCheckResult
  onRecheck: () => void
  recheckDisabled?: boolean
}>(function LongVerdictCard({ result: r, onRecheck, recheckDisabled }, headingRef) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const tc = t.check
  const tl = tc.long
  const style = useLongVerdictStyle()(r.verdict)
  const ai = r.ai_assessment
  const assetLabel = (tl.assetType as Record<string, string>)[r.asset_type] ?? r.asset_type
  const stamp = [
    r.cached ? tc.cached : null,
    fill(tc.checkedAt, { time: etTime(r.checked_at, locale) }),
    fill(tl.dataAsOf, { date: shortDate(r.data_as_of, locale, true) }),
  ].filter(Boolean).join(' · ')

  const lists: { title: string; items: string[] }[] = ai ? [
    { title: tl.strengths, items: ai.strengths },
    { title: tl.concerns, items: ai.concerns },
    { title: tl.whatToWatch, items: ai.what_to_watch },
  ].filter((l) => l.items.length > 0) : []

  return (
    <section
      aria-labelledby="check-verdict"
      className="rounded-2xl p-4 sm:p-5 md:p-6 flex flex-col gap-4 min-w-0"
      style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.border}`, borderLeft: `4px solid ${style.color}` }}
    >
      <div className="flex flex-col sm:flex-row sm:flex-wrap sm:items-start sm:justify-between gap-3">
        <div className="flex items-start gap-3 min-w-0">
          <style.Icon size={32} aria-hidden="true" className="shrink-0 mt-0.5" style={{ color: style.color }} />
          <div className="flex flex-col gap-1 min-w-0">
            <h2
              id="check-verdict"
              ref={headingRef}
              tabIndex={-1}
              className="text-[22px] md:text-[28px] font-semibold tracking-tight outline-none break-words"
              style={{ color: style.color }}
            >
              {(tl.verdict as Record<string, string>)[r.verdict] ?? r.verdict}
            </h2>
            <p className="text-[13px] break-words" style={{ color: theme.colors.textSub }}>
              <span style={{ ...mono, color: theme.colors.text }}>{r.symbol}</span>
              {r.name && <> · {r.name}</>}
              {' · '}{assetLabel}
              {r.price != null && <> · {nativePrice(r.price, r.symbol, r.currency)}</>}
            </p>
            <p className="text-[12px]" style={{ color: theme.colors.textSub }}>
              {r.verdict_source === 'ai' && ai
                ? fill(tl.source.ai, { confidence: ai.confidence })
                : tl.source.scorecard}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-[12px]" style={{ color: theme.colors.textSub }}>
          <span>{stamp}</span>
          <button
            type="button"
            onClick={onRecheck}
            disabled={recheckDisabled}
            aria-label={fill(tc.recheckLabel, { symbol: r.symbol })}
            className="inline-flex items-center gap-1.5 min-h-11 px-3 rounded-lg text-[13px] font-medium disabled:opacity-50 focus-visible:outline focus-visible:outline-2"
            style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.primary, outlineColor: theme.colors.primary }}
          >
            <RefreshCw size={14} aria-hidden="true" />
            {tc.recheck}
          </button>
        </div>
      </div>

      {ai && (
        <div className="flex flex-col gap-3">
          <p className="text-[15px] leading-relaxed" style={{ color: theme.colors.text }}>{ai.summary}</p>
          {lists.length > 0 && (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              {lists.map((l) => (
                <div key={l.title} className="rounded-[10px] p-3 flex flex-col gap-1.5 min-w-0" style={{ backgroundColor: theme.colors.surfaceAlt }}>
                  <h3 className="text-[13px] font-semibold" style={{ color: theme.colors.text }}>{l.title}</h3>
                  <ul className="flex flex-col gap-1 list-disc pl-5">
                    {l.items.map((x, i) => (
                      <li key={i} className="text-[13px] break-words" style={{ color: theme.colors.text }}>{x}</li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}
          {ai.dca_note && (
            <div className="flex flex-col gap-1">
              <h3 className="text-[13px] font-semibold" style={{ color: theme.colors.text }}>{tl.dca}</h3>
              <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{ai.dca_note}</p>
            </div>
          )}
          {locale !== 'en' && <p className="text-[11px]" style={{ color: theme.colors.textHint }}>{tl.aiEnglish}</p>}
        </div>
      )}

      {r.notes.length > 0 && (
        <ul className="flex flex-col gap-1">
          {r.notes.map((n) => (
            <li key={n.code} className="text-[12px]" style={{ color: theme.colors.textSub }}>{longText(n, 'notes', t)}</li>
          ))}
        </ul>
      )}
    </section>
  )
})
