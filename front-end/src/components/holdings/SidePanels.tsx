'use client'

import { memo, useId, useMemo, useState } from 'react'
import { ListChecks, Sparkles } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { fill, shortDate } from '@/lib/insights'
import { Panel } from '@/components/insights/Panel'
import { ProgressBar } from '@/components/ui/ProgressBar'
import { useAllocateIdeas, type HoldingsError } from '@/hooks/useHoldings'
import { errorText, ideaReason, noteText, pct, spct, useMaskedMoney, useToneColor, verdictTone } from './format'
import type { AllocateIdea, HoldingsResponse, ReviewJob } from '@/types/holdings'

const btnCls = 'min-h-[44px] px-4 rounded-xl text-[14px] font-semibold flex items-center justify-center gap-2 transition-opacity disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2'

// ── Totals ──

export function TotalsCard({ data }: { data: HoldingsResponse }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const th = t.holdings
  const tot = data.totals
  const mm = useMaskedMoney()
  const gainColor = (tot.unrealized_cad ?? 0) >= 0 ? theme.colors.up : theme.colors.down
  return (
    <Panel title={th.totals.title}>
      {tot.value_cad == null ? (
        <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{th.totals.noShares}</p>
      ) : (
        <div className="flex flex-col gap-2">
          <p className="text-[26px] font-bold tabular-nums" style={{ color: theme.colors.text }}>{mm(tot.value_cad, 'CAD', locale)}</p>
          {tot.unrealized_cad != null && (
            <p className="text-[13px] tabular-nums" style={{ color: gainColor }}>
              {th.totals.gain}: {mm(tot.unrealized_cad, 'CAD', locale)} ({spct(tot.unrealized_pct, 1)})
            </p>
          )}
          <p className="text-[12px]" style={{ color: theme.colors.textSub }}>
            {fill(th.totals.coverage, { n: tot.count_with_shares, total: tot.count })} {th.totals.weightNote}
          </p>
          <p className="text-[12px]" style={{ color: tot.fx_missing ? theme.colors.warning : theme.colors.textSub }}>
            {tot.fx_missing ? th.totals.fxMissing : tot.usdcad ? fill(th.totals.fx, { rate: tot.usdcad.toFixed(4) }) : null}
          </p>
        </div>
      )}
    </Panel>
  )
}

// ── Reviews ──

export function ReviewPanel({ data, job, running, error, onReviewAll }: {
  data: HoldingsResponse
  job: ReviewJob | null
  running: boolean
  error: HoldingsError | null
  onReviewAll: () => void
}) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const th = t.holdings
  const ra = data.review_all
  const reviewed = data.items.filter((h) => h.last_review).length
  const failed = job?.results.filter((r) => r.error).length ?? 0
  return (
    <Panel title={th.review.title} subtitle={th.review.subtitle}>
      <div className="flex flex-col gap-3">
        <p className="text-[13px]" style={{ color: theme.colors.textSub }}>
          {fill(th.review.reviewedCount, { n: reviewed, total: data.count })}
        </p>
        <button type="button" onClick={onReviewAll} disabled={running || !ra.allowed || data.count === 0}
          className={btnCls}
          style={{ backgroundColor: theme.colors.primary, color: theme.colors.surface, outlineColor: theme.colors.primary }}>
          <ListChecks size={16} aria-hidden="true" />
          {th.review.all}
        </button>
        <p className="text-[12px]" style={{ color: theme.colors.textSub }}>
          {ra.allowed ? fill(th.review.allHint, { days: ra.days }) : fill(th.review.nextAt, { date: shortDate(ra.next_allowed_at, locale, true) })}
        </p>
        {job && (
          <div role="status" aria-live="polite" className="flex flex-col gap-1.5">
            {job.status === 'running' ? (
              <>
                <p className="text-[13px]" style={{ color: theme.colors.text }}>
                  {job.current ? fill(th.review.running, { current: job.current, done: job.done, total: job.total }) : th.review.starting}
                </p>
                <ProgressBar value={job.pct} height={4} />
              </>
            ) : (
              <p className="text-[13px]" style={{ color: theme.colors.text }}>
                {fill(th.review.done, { n: job.done - failed })}
                {failed ? ` ${fill(th.review.failedN, { n: failed })}` : ''}
              </p>
            )}
          </div>
        )}
        {error && (
          <p role="alert" className="text-[13px]" style={{ color: theme.colors.down }}>
            {errorText(error.code, th, { date: shortDate(error.nextAllowedAt, locale, true) })}
          </p>
        )}
      </div>
    </Panel>
  )
}

// ── Where could new cash go? ──

const IdeaItem = memo(function IdeaItem({ idea }: { idea: AllocateIdea }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const th = t.holdings
  const tone = useToneColor()
  const tierTone = idea.tier === 'consider' ? 'up' : idea.tier === 'caution' ? 'down' : 'neutral'
  const vColor = tone(verdictTone(idea.verdict))
  return (
    <li className="flex gap-3 py-3 min-w-0" style={{ borderTop: `1px solid ${theme.colors.border}` }}>
      <span className="w-6 shrink-0 text-right text-[13px] font-semibold tabular-nums" style={{ color: theme.colors.textHint }}>
        {idea.rank}
      </span>
      <div className="min-w-0 flex-1 flex flex-col gap-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="font-mono font-semibold text-[14px]" style={{ color: theme.colors.text }}>{idea.symbol}</span>
          <span className="text-[12px] font-medium px-2 py-0.5 rounded-full"
            style={{ backgroundColor: tierTone === 'neutral' ? theme.colors.surfaceAlt : tone(tierTone) + '1A', color: tone(tierTone) }}>
            {th.allocate.tiers[idea.tier]}
          </span>
          {idea.verdict && <span className="text-[12px]" style={{ color: vColor }}>{th.verdictShort[idea.verdict]}</span>}
          {idea.source === 'watchlist' && <span className="text-[12px]" style={{ color: theme.colors.textSub }}>{th.allocate.watchlist}</span>}
          {idea.weight_pct != null && (
            <span className="text-[12px] tabular-nums" style={{ color: theme.colors.textSub }}>{fill(th.allocate.weight, { n: pct(idea.weight_pct, 0) })}</span>
          )}
        </div>
        <p className="text-[13px] break-words" style={{ color: theme.colors.textSub }}>{ideaReason(idea.factors, th)}</p>
      </div>
    </li>
  )
})

export function AllocatePanel({ hasHoldings, reviewedCount }: { hasHoldings: boolean; reviewedCount: number }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const th = t.holdings
  const wlId = useId()
  const [open, setOpen] = useState(false)
  const [withWatchlist, setWithWatchlist] = useState(false)
  const q = useAllocateIdeas(open && hasHoldings, withWatchlist)
  const notes = useMemo(() => q.data?.notes ?? [], [q.data])
  return (
    <Panel title={th.allocate.title} subtitle={th.allocate.subtitle}>
      <div className="flex flex-col gap-3">
        {!hasHoldings ? (
          <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{th.allocate.empty}</p>
        ) : !open ? (
          <button type="button" onClick={() => setOpen(true)} className={btnCls}
            style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.primary, outlineColor: theme.colors.primary }}>
            <Sparkles size={16} aria-hidden="true" />
            {th.allocate.show}
          </button>
        ) : (
          <>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <label htmlFor={wlId} className="flex items-center gap-2 min-h-[44px] text-[13px] cursor-pointer" style={{ color: theme.colors.text }}>
                <input id={wlId} type="checkbox" checked={withWatchlist} onChange={(e) => setWithWatchlist(e.target.checked)}
                  className="w-5 h-5" style={{ accentColor: theme.colors.primary }} />
                {th.allocate.includeWatchlist}
              </label>
              <button type="button" onClick={() => q.refetch()} disabled={q.isFetching}
                className="min-h-[44px] px-3 rounded-lg text-[13px] font-medium focus-visible:outline focus-visible:outline-2 disabled:opacity-50"
                style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.text, outlineColor: theme.colors.primary }}>
                {th.allocate.refresh}
              </button>
            </div>
            {reviewedCount === 0 && (
              <p className="text-[12px]" style={{ color: theme.colors.warning }}>{th.allocate.reviewFirst}</p>
            )}
            {q.isLoading && <p role="status" className="text-[13px]" style={{ color: theme.colors.textSub }}>{th.allocate.loading}</p>}
            {q.error && <p role="alert" className="text-[13px]" style={{ color: theme.colors.down }}>{errorText('internal', th)}</p>}
            {q.data && (
              <ol className="flex flex-col" aria-label={th.allocate.title}>
                {q.data.ideas.map((i) => <IdeaItem key={`${i.source}-${i.symbol}`} idea={i} />)}
              </ol>
            )}
            {notes.length > 0 && (
              <div className="flex flex-col gap-2 pt-2" style={{ borderTop: `1px solid ${theme.colors.border}` }}>
                <h3 className="text-[14px] font-semibold" style={{ color: theme.colors.text }}>{th.allocate.overlapTitle}</h3>
                <ul className="flex flex-col gap-1.5 list-disc pl-5">
                  {notes.map((n) => (
                    <li key={n.code} className="text-[13px] break-words" style={{ color: theme.colors.textSub }}>{noteText(n, th)}</li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
        <p className="text-[12px] rounded-xl p-3" style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.textSub }}>
          {th.allocate.caveat}
        </p>
      </div>
    </Panel>
  )
}
