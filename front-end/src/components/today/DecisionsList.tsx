'use client'

import { useMemo, useState } from 'react'
import Link from 'next/link'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { Panel } from '@/components/insights/Panel'
import { fill, formatReason, num, DASH } from '@/lib/insights'
import type { TodayDecision } from '@/types/insights'
import type en from '@/lib/i18n/en.json'

type Filter = 'all' | 'bought' | 'skipped'

/** "BUY → HOLD" style routine → decision model summary. */
export function aiChain(d: Pick<TodayDecision, 'ai_status' | 'routine_signal' | 'decision_signal' | 'decision_overturned'>, t: typeof en): string {
  const dd = t.today.decisions
  if (!d.routine_signal && (!d.ai_status || d.ai_status === 'skipped')) return dd.aiNotCalled
  const routine = d.routine_signal ?? DASH
  if (d.decision_overturned !== null && d.decision_overturned !== undefined) return `${routine} → ${d.decision_signal ?? DASH}`
  if (routine === 'BUY') return `BUY → ${DASH}`
  return routine
}

function bucketLabel(b: string | null, t: typeof en): string {
  if (b === 'HIGH_RISK') return t.signal.highRisk
  if (b === 'SAFE_INCOME') return t.signal.safeIncome
  return b ?? ''
}

export function DecisionsList({ decisions, decisionsLogged = true }: { decisions: TodayDecision[]; decisionsLogged?: boolean }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const d = t.today.decisions
  const [filter, setFilter] = useState<Filter>('all')

  const counts = useMemo(() => ({
    all: decisions.length,
    bought: decisions.filter((x) => x.decision === 'ENTER').length,
    skipped: decisions.filter((x) => x.decision !== 'ENTER').length,
  }), [decisions])
  const rows = useMemo(() => decisions.filter((x) =>
    filter === 'all' ? true : filter === 'bought' ? x.decision === 'ENTER' : x.decision !== 'ENTER'), [decisions, filter])

  const badge = (x: TodayDecision) => {
    if (x.decision === 'ENTER') return { text: d.boughtBadge, color: theme.colors.bg, bg: theme.colors.up }
    if (x.decision === 'SKIP') return { text: d.skippedBadge, color: theme.colors.text, bg: theme.colors.surfaceAlt }
    if (!decisionsLogged) return { text: d.noLogBadge, color: theme.colors.textSub, bg: 'transparent' }
    return { text: d.noDecisionBadge, color: theme.colors.textSub, bg: 'transparent' }
  }
  const why = (x: TodayDecision) =>
    (x.reason ? formatReason(x.reason, t) : decisionsLogged ? d.noDecision : d.noLog)

  const filterButtons: { key: Filter; label: string }[] = [
    { key: 'all', label: fill(d.all, { n: counts.all }) },
    { key: 'bought', label: fill(d.bought, { n: counts.bought }) },
    { key: 'skipped', label: fill(d.skipped, { n: counts.skipped }) },
  ]
  const cols = 'md:grid-cols-[110px_120px_minmax(0,1fr)_150px_64px_56px]'

  return (
    <Panel
      padded={false}
      title={<><span className="hidden md:inline">{d.title}</span><span className="md:hidden">{d.mobileTitle}</span></>}
      right={
        <div role="group" aria-label={d.filterLabel} className="flex gap-1.5">
          {filterButtons.map((b) => (
            <button
              key={b.key}
              type="button"
              aria-pressed={filter === b.key}
              onClick={() => setFilter(b.key)}
              className="h-8 px-3 rounded-lg text-[13px] tabular-nums transition-colors focus-visible:outline focus-visible:outline-2"
              style={{
                backgroundColor: filter === b.key ? theme.colors.surfaceAlt : 'transparent',
                color: filter === b.key ? theme.colors.text : theme.colors.textSub,
                outlineColor: theme.colors.primary,
              }}
            >
              {b.label}
            </button>
          ))}
        </div>
      }
    >
      {decisions.length === 0 ? (
        <p className="px-5 md:px-6 pb-2 text-sm" style={{ color: theme.colors.textSub }}>{d.empty}</p>
      ) : (
        <>
          <div
            className={`hidden md:grid ${cols} gap-3 px-6 py-2.5 text-[12px]`}
            style={{ color: theme.colors.textSub, borderTop: `1px solid ${theme.colors.border}`, borderBottom: `1px solid ${theme.colors.border}` }}
            aria-hidden="true"
          >
            <span>{d.colSymbol}</span><span>{d.colDecision}</span><span>{d.colWhy}</span>
            <span>{d.colAi}</span><span>{d.colPwin}</span><span>{d.colRr}</span>
          </div>
          {!decisionsLogged && (
            <p className="px-5 md:px-6 pt-3 text-[13px]" style={{ color: theme.colors.textSub }}>{d.noLogNote}</p>
          )}
          {rows.length === 0 && (
            <p className="px-5 md:px-6 py-4 text-sm" style={{ color: theme.colors.textSub }}>{d.emptyFilter}</p>
          )}
          <ul className="flex flex-col gap-2.5 px-4 md:px-0 md:gap-0">
            {rows.map((x) => {
              const b = badge(x)
              return (
                <li key={x.symbol}>
                  <Link
                    href={`/signals/${encodeURIComponent(x.symbol)}`}
                    className={`grid grid-cols-1 ${cols} gap-2 md:gap-3 items-center rounded-[14px] md:rounded-none p-3.5 md:px-6 md:py-3 border md:border-0 md:border-b bg-[var(--card-bg)] md:bg-transparent border-[var(--line)] transition-opacity hover:opacity-90 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2`}
                    style={{
                      color: theme.colors.text,
                      outlineColor: theme.colors.primary,
                      // mobile = stacked card, md+ = table row with a hairline
                      ['--card-bg' as string]: theme.colors.surfaceAlt,
                      ['--line' as string]: theme.colors.border,
                    }}
                  >
                    <span className="flex items-center justify-between md:flex-col md:items-start gap-0.5">
                      <span className="flex flex-col">
                        <span className="text-[15px] md:text-[14px] font-medium" style={{ fontFamily: 'var(--font-mono)' }}>{x.symbol}</span>
                        <span className="hidden md:block text-[11px]" style={{ color: theme.colors.textSub }}>{bucketLabel(x.bucket, t)}</span>
                      </span>
                      <span className="md:hidden text-[11px] font-bold rounded-md px-2 py-1" style={{ color: b.color, backgroundColor: b.bg, border: b.bg === 'transparent' ? `1px solid ${theme.colors.border}` : undefined }}>{b.text}</span>
                    </span>
                    <span className="hidden md:inline-flex justify-self-start text-[12px] font-semibold rounded-md px-2 py-1" style={{ color: b.color, backgroundColor: b.bg, border: b.bg === 'transparent' ? `1px solid ${theme.colors.border}` : undefined }}>
                      {b.text}
                    </span>
                    <span className="text-[13px] leading-snug" style={{ color: theme.colors.text }}>{why(x)}</span>
                    <span className="text-[12px]" style={{ color: theme.colors.textSub, fontFamily: 'var(--font-mono)' }}>
                      <span className="md:hidden">
                        {aiChain(x, t)}
                        {x.p_win != null && ` · p_win ${num(x.p_win)}`}
                        {x.rr != null && ` · R:R ${num(x.rr, 1)}`}
                      </span>
                      <span className="hidden md:inline">{aiChain(x, t)}</span>
                    </span>
                    <span className="hidden md:inline text-[13px] tabular-nums" style={{ fontFamily: 'var(--font-mono)' }}>{num(x.p_win)}</span>
                    <span className="hidden md:inline text-[13px] tabular-nums" style={{ fontFamily: 'var(--font-mono)' }}>{num(x.rr, 1)}</span>
                  </Link>
                </li>
              )
            })}
          </ul>
        </>
      )}
    </Panel>
  )
}
