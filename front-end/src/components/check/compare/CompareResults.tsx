'use client'

import { forwardRef, memo, useMemo } from 'react'
import Link from 'next/link'
import { ArrowUpRight, RefreshCw, Trophy } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { Panel } from '@/components/insights/Panel'
import { useVerdictStyle } from '@/components/check/CheckResultView'
import { useLongVerdictStyle } from '@/components/check/long/format'
import { checkHref } from '@/lib/check'
import { fill, nativePrice } from '@/lib/insights'
import { formatMetricSub, formatMetricValue, isBest, metricLabel } from './format'
import type {
  CheckMode, CheckVerdict, CompareIdentity, CompareJob, CompareMetric, Comparison, CompareSummary, LongVerdict,
} from '@/types/check'

function useVerdictChip(mode: CheckMode) {
  const short = useVerdictStyle()
  const long = useLongVerdictStyle()
  const t = useI18nStore((s) => s.t)
  return (v: string | null | undefined) => {
    if (!v) return null
    const st = mode === 'long' ? long(v as LongVerdict) : short(v as CheckVerdict)
    const dict = (mode === 'long' ? t.check.long.verdict : t.check.verdict) as Record<string, string>
    return { ...st, label: dict[v] ?? v }
  }
}

function VerdictChip({ mode, verdict }: { mode: CheckMode; verdict: string | null | undefined }) {
  const chip = useVerdictChip(mode)(verdict)
  const theme = useTheme()
  if (!chip) return null
  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[12px] font-medium max-w-full"
      style={{ color: chip.color, border: `1px solid ${chip.color}`, backgroundColor: theme.colors.surface }}
    >
      <chip.Icon size={13} aria-hidden="true" className="shrink-0" />
      <span className="truncate">{chip.label}</span>
    </span>
  )
}

function BestMarker() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  return (
    <span
      className="inline-flex items-center gap-0.5 px-1.5 py-px rounded text-[10.5px] font-semibold shrink-0"
      style={{ color: theme.colors.up, border: `1px solid ${theme.colors.up}` }}
    >
      <Trophy size={10} aria-hidden="true" />
      {t.check.compare.best}
    </span>
  )
}

const MetricCell = memo(function MetricCell({ m, sym }: { m: CompareMetric; sym: string }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const best = isBest(m, sym)
  const sub = formatMetricSub(m, sym, t)
  return (
    <span className="flex flex-col items-start gap-0.5 min-w-0">
      <span className="flex flex-wrap items-center gap-1.5">
        <span
          className="text-[13.5px] tabular-nums"
          style={{ color: best ? theme.colors.up : theme.colors.text, fontWeight: best ? 600 : 400, fontFamily: 'var(--font-mono)' }}
        >
          {formatMetricValue(m, sym, t)}
        </span>
        {best && <BestMarker />}
      </span>
      {sub && <span className="text-[11.5px]" style={{ color: theme.colors.textSub }}>{sub}</span>}
    </span>
  )
})

function FullCheckLink({ sym, mode }: { sym: string; mode: CheckMode }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  return (
    <Link
      href={checkHref(sym, mode)}
      aria-label={fill(t.check.compare.fullCheckLabel, { symbol: sym })}
      className="inline-flex items-center gap-1 min-h-11 text-[12.5px] font-medium hover:underline focus-visible:outline focus-visible:outline-2 rounded"
      style={{ color: theme.colors.primary, outlineColor: theme.colors.primary }}
    >
      {t.check.compare.fullCheck}
      <ArrowUpRight size={14} aria-hidden="true" />
    </Link>
  )
}

function SymbolHead({ id, mode }: { id: CompareIdentity; mode: CheckMode }) {
  const theme = useTheme()
  return (
    <span className="flex flex-col items-start gap-1 min-w-0">
      <span className="text-[15px] font-semibold" style={{ color: theme.colors.text, fontFamily: 'var(--font-mono)' }}>{id.symbol}</span>
      {id.name && <span className="text-[12px] font-normal truncate max-w-full" style={{ color: theme.colors.textSub }}>{id.name}</span>}
      <span className="text-[12px] font-normal tabular-nums" style={{ color: theme.colors.textSub }}>{nativePrice(id.price, id.symbol, id.currency)}</span>
      <VerdictChip mode={mode} verdict={id.verdict} />
    </span>
  )
}

function RankingCard({ summary, cmp, mode }: { summary: CompareSummary; cmp: Comparison; mode: CheckMode }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const tc = t.check.compare
  const chip = useVerdictChip(mode)
  const total = cmp.metrics.filter((m) => m.better).length
  const ai = summary.source === 'ai'
  const reason = (sym: string) => {
    if (ai && summary.per_symbol[sym]) return summary.per_symbol[sym]
    return fill(tc.perSymbolFallback, {
      verdict: chip(cmp.identity[sym]?.verdict)?.label ?? null,
      n: cmp.best_counts[sym] ?? 0,
      total,
    })
  }
  const noteText = summary.note ? ((tc.notes as Record<string, string>)[summary.note.code] ?? summary.note.text) : null
  return (
    <Panel title={tc.rankingTitle} subtitle={ai ? tc.rankingAi : tc.rankingRules}>
      <div className="flex flex-col gap-4">
        <ol className="flex flex-col gap-2">
          {summary.ranking.map((sym, i) => {
            const c = chip(cmp.identity[sym]?.verdict)
            return (
              <li key={sym} className="flex items-start gap-3 min-w-0">
                <span
                  className="inline-flex items-center justify-center w-7 h-7 rounded-full text-[13px] font-semibold shrink-0"
                  style={{ backgroundColor: i === 0 ? theme.colors.up : theme.colors.surfaceAlt, color: i === 0 ? theme.colors.surface : theme.colors.text }}
                  aria-hidden="true"
                >
                  {i + 1}
                </span>
                <span className="flex flex-col gap-0.5 min-w-0">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="sr-only">{i + 1}.</span>
                    <span className="text-[14px] font-semibold" style={{ color: theme.colors.text, fontFamily: 'var(--font-mono)' }}>{sym}</span>
                    {c && <span className="text-[12px]" style={{ color: c.color }}>{c.label}</span>}
                  </span>
                  <span className="text-[13px]" style={{ color: theme.colors.textSub }}>{reason(sym)}</span>
                </span>
              </li>
            )
          })}
        </ol>
        {ai && summary.summary && (
          <div className="flex flex-col gap-1">
            <p className="text-[14px] leading-relaxed" style={{ color: theme.colors.text }} lang="en">{summary.summary}</p>
            {locale !== 'en' && <p className="text-[11.5px]" style={{ color: theme.colors.textHint }}>{tc.aiEnglish}</p>}
          </div>
        )}
        {noteText && <p className="text-[12.5px]" style={{ color: theme.colors.warning }}>{noteText}</p>}
        <ul className="flex flex-col gap-0.5">
          {ai && summary.caveats.filter((c) => !/financial advice/i.test(c)).map((c) => (
            <li key={c} className="text-[12px]" style={{ color: theme.colors.textSub }} lang="en">{c}</li>
          ))}
          <li className="text-[12px]" style={{ color: theme.colors.textSub }}>{tc.caveat}</li>
        </ul>
      </div>
    </Panel>
  )
}

/** Summary card, then a side-by-side table (≥ 640px) or swipeable cards. */
export const CompareResults = forwardRef<HTMLHeadingElement, {
  job: CompareJob
  onRerun: () => void
  rerunDisabled?: boolean
}>(function CompareResults({ job, onRerun, rerunDisabled }, headingRef) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const tc = t.check.compare
  const mode = job.mode
  const cmp = job.comparison
  const syms = useMemo(() => cmp?.symbols ?? [], [cmp])
  const rows = useMemo(() => {
    const out: { group: string; metrics: CompareMetric[] }[] = []
    for (const m of (cmp?.metrics ?? []).filter((x) => x.key !== 'verdict')) {
      const last = out[out.length - 1]
      if (last && last.group === m.group) last.metrics.push(m)
      else out.push({ group: m.group, metrics: [m] })
    }
    return out
  }, [cmp])
  const verdictMetric = cmp?.metrics.find((m) => m.key === 'verdict')
  const ranking = job.summary?.ranking ?? syms
  const cardOrder = useMemo(() => [...ranking, ...syms.filter((s) => !ranking.includes(s))], [ranking, syms])
  const groupLabel = (g: string) => (tc.groups as Record<string, string>)[g] ?? g

  if (!cmp || syms.length < 2) return null

  return (
    <div className="flex flex-col gap-4 md:gap-6">
      <h2 ref={headingRef} tabIndex={-1} className="sr-only">{fill(tc.progressTitle, { symbols: syms.join(' · ') })}</h2>
      {job.summary && <RankingCard summary={job.summary} cmp={cmp} mode={mode} />}

      <Panel
        title={tc.tableTitle}
        right={(
          <button
            type="button"
            onClick={onRerun}
            disabled={rerunDisabled}
            aria-label={tc.againLabel}
            className="inline-flex items-center gap-1.5 min-h-11 px-2 -my-2 text-[12.5px] font-medium disabled:opacity-60 hover:underline focus-visible:outline focus-visible:outline-2 rounded"
            style={{ color: theme.colors.primary, outlineColor: theme.colors.primary }}
          >
            <RefreshCw size={14} aria-hidden="true" />
            {tc.again}
          </button>
        )}
      >
        {/* Desktop / tablet: real table */}
        <div className="hidden sm:block overflow-x-auto">
          <table className="w-full border-collapse text-left">
            <caption className="sr-only">{fill(tc.tableCaption, { symbols: syms.join(', ') })}</caption>
            <thead>
              <tr>
                <th scope="col" className="py-2 pr-3 align-bottom text-[12px] font-medium w-[34%]" style={{ color: theme.colors.textSub }}>{tc.metric}</th>
                {syms.map((s) => (
                  <th key={s} scope="col" className="py-2 px-3 align-top" style={{ borderLeft: `1px solid ${theme.colors.border}` }}>
                    {cmp.identity[s] && <SymbolHead id={cmp.identity[s]} mode={mode} />}
                    {verdictMetric && isBest(verdictMetric, s) && <span className="block mt-1"><BestMarker /></span>}
                  </th>
                ))}
              </tr>
            </thead>
            {rows.map((g) => (
              <tbody key={g.group}>
                <tr>
                  <th scope="colgroup" colSpan={syms.length + 1} className="pt-4 pb-1 text-[11.5px] font-semibold uppercase tracking-wide" style={{ color: theme.colors.textHint }}>
                    {groupLabel(g.group)}
                  </th>
                </tr>
                {g.metrics.map((m) => (
                  <tr key={m.key} style={{ borderTop: `1px solid ${theme.colors.border}` }}>
                    <th scope="row" className="py-2 pr-3 text-[13px] font-normal align-top" style={{ color: theme.colors.textSub }}>{metricLabel(m.key, t)}</th>
                    {syms.map((s) => (
                      <td key={s} className="py-2 px-3 align-top" style={{ borderLeft: `1px solid ${theme.colors.border}` }}>
                        <MetricCell m={m} sym={s} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            ))}
            <tbody>
              <tr style={{ borderTop: `1px solid ${theme.colors.border}` }}>
                <td className="py-1" />
                {syms.map((s) => (
                  <td key={s} className="py-1 px-3" style={{ borderLeft: `1px solid ${theme.colors.border}` }}>
                    <FullCheckLink sym={s} mode={mode} />
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>

        {/* Phone: swipeable cards (scroll-snap), best-ranked first */}
        <div className="sm:hidden flex flex-col gap-2">
          <p className="text-[12px]" style={{ color: theme.colors.textSub }}>{tc.swipeHint}</p>
          <ul className="flex gap-3 overflow-x-auto snap-x snap-mandatory overscroll-x-contain pb-2" aria-label={tc.tableTitle}>
            {cardOrder.map((s, i) => (
              <li
                key={s}
                className="snap-start shrink-0 w-[86%] rounded-[14px] p-4 flex flex-col gap-3"
                style={{ backgroundColor: theme.colors.surfaceAlt, border: `1px solid ${theme.colors.border}` }}
                aria-label={fill(tc.cardLabel, { symbol: s, rank: i + 1, total: cardOrder.length })}
              >
                {cmp.identity[s] && <SymbolHead id={cmp.identity[s]} mode={mode} />}
                {rows.map((g) => (
                  <div key={g.group} className="flex flex-col gap-1">
                    <h3 className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: theme.colors.textHint }}>{groupLabel(g.group)}</h3>
                    <dl className="flex flex-col">
                      {g.metrics.map((m) => (
                        <div key={m.key} className="flex items-start justify-between gap-3 py-1.5" style={{ borderTop: `1px solid ${theme.colors.border}` }}>
                          <dt className="text-[12.5px] min-w-0" style={{ color: theme.colors.textSub }}>{metricLabel(m.key, t)}</dt>
                          <dd className="text-right min-w-0 flex justify-end"><MetricCell m={m} sym={s} /></dd>
                        </div>
                      ))}
                    </dl>
                  </div>
                ))}
                <FullCheckLink sym={s} mode={mode} />
              </li>
            ))}
          </ul>
        </div>
      </Panel>
    </div>
  )
})
