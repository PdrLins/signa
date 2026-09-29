'use client'

import { useState } from 'react'
import { Check, X, Minus } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { Panel } from '@/components/insights/Panel'
import { PriceChart } from '@/components/charts/PriceChart'
import { fill, formatReason, num, compactUsd, nativePrice, money, shortDate, etTime, signedFracPct, DASH } from '@/lib/insights'
import type { SignalTrail, TechCheck } from '@/types/insights'
import type en from '@/lib/i18n/en.json'

type T = typeof en

function Step({ n, title, right, last, active, children }: {
  n: number
  title: string
  right?: React.ReactNode
  last?: boolean
  active?: boolean
  children: React.ReactNode
}) {
  const theme = useTheme()
  return (
    <li className="grid grid-cols-[32px_minmax(0,1fr)] gap-3 md:gap-4">
      <div className="flex flex-col items-center" aria-hidden="true">
        <span
          className="w-7 h-7 rounded-full grid place-items-center text-[13px] font-semibold"
          style={active
            ? { backgroundColor: theme.colors.up, color: theme.colors.bg }
            : { backgroundColor: theme.colors.surfaceAlt, border: `2px solid ${theme.colors.up}`, color: theme.colors.text }}
        >
          {n}
        </span>
        {!last && <span className="flex-1 w-0.5 mt-1" style={{ backgroundColor: theme.colors.surfaceAlt }} />}
      </div>
      <div className={`flex flex-col gap-2.5 min-w-0 ${last ? '' : 'pb-6'}`}>
        <div className="flex flex-wrap justify-between gap-x-3 gap-y-1">
          <h3 className="text-[15px] font-semibold" style={{ color: theme.colors.text }}>{title}</h3>
          {right}
        </div>
        {children}
      </div>
    </li>
  )
}

function checkText(c: TechCheck, t: T): string {
  const f = t.trail.filter
  const v = c.value
  const lim = c.limit
  switch (c.key) {
    case 'above_sma200':
      return v == null ? fill(f.noData, { label: 'SMA200' }) : fill(c.ok === false ? f.above_sma200_fail : f.above_sma200, { value: v.toFixed(1) })
    case 'sma50_above_sma200':
      return c.ok === false ? f.sma50_above_sma200_fail : f.sma50_above_sma200
    case 'rsi':
      return v == null ? fill(f.noData, { label: 'RSI' }) : fill(f.rsi, { value: v.toFixed(0), limit: lim })
    case 'extension_sma50':
      return v == null ? fill(f.noData, { label: 'SMA50' }) : fill(f.extension_sma50, { value: v.toFixed(1), limit: lim })
    case 'liquidity':
      return v == null ? fill(f.noData, { label: '$ volume' }) : fill(f.liquidity, { value: compactUsd(v), limit: compactUsd(lim) })
    case 'blockers':
      return c.ok === false ? f.blockers_fail : f.blockers
    default:
      return c.key
  }
}

function hostLabel(url: string): string {
  try {
    const u = new URL(url)
    const host = u.hostname.replace(/^www\./, '')
    const path = u.pathname.split('/').filter(Boolean)[0]
    return path && host !== 'x.com' && host !== 'twitter.com' ? `${host} · ${decodeURIComponent(path).slice(0, 24)}` : host
  } catch {
    return url.slice(0, 32)
  }
}

const VISIBLE_CITATIONS = 4

/** Optional overrides so other flows (e.g. the on-demand "Check a stock"
 *  page) can render the same trail without a stored signal / order. */
export interface DecisionTrailOptions {
  /** Panel title (default: "Decision trail · {date} scan"). */
  title?: string
  /** Step 5 title (default: "Risk check and order"). */
  orderTitle?: string
  /** Step 5 status label + highlight (default: Bought / Skipped / Not evaluated). */
  orderStatus?: { label: string; active: boolean }
  /** Hide the "What happened next" panel (no stored outcomes). */
  showOutcomes?: boolean
}

export function DecisionTrail({ trail, options = {} }: { trail: SignalTrail; options?: DecisionTrailOptions }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const tr = t.trail
  const [showAll, setShowAll] = useState(false)
  const verdictColor = (sig: string | null | undefined) => (sig === 'BUY' ? theme.colors.up : theme.colors.textSub)
  const mono = { fontFamily: 'var(--font-mono)' }

  // 1. technical filter
  const tf = trail.tech_filter
  const passedCount = tf ? tf.checks.filter((c) => c.ok === true).length : 0
  // 2. grok
  const g = trail.grok
  const cites = g?.citations ?? []
  const shownCites = showAll ? cites : cites.slice(0, VISIBLE_CITATIONS)
  // 3/4. models
  const r = trail.routine
  const dm = trail.decision_model
  const verdictLine = (sig: string | null, conf: number | null, pwin: number | null) =>
    [sig ?? DASH, conf != null ? fill(tr.conf, { c: Math.round(conf) }) : null, pwin != null ? fill(tr.pwin, { p: num(pwin) }) : null].filter(Boolean).join(' · ')
  // 5. order
  const dec = trail.decision
  const o = trail.order
  const bought = options.orderStatus ? options.orderStatus.active : dec?.decision === 'ENTER'
  const showOutcomes = options.showOutcomes ?? true

  const scanWhen = `${shortDate(trail.created_at, locale)}, ${etTime(trail.created_at, locale)}`

  const orderTiles: { k: string; v: string }[] = o ? [
    { k: tr.order.entry, v: nativePrice(o.fill ?? o.ref_price, trail.symbol) },
    { k: tr.order.stop, v: nativePrice(o.stop, trail.symbol) },
    { k: tr.order.target, v: nativePrice(o.target, trail.symbol) },
    { k: tr.order.rr, v: num(o.rr, 1) },
    { k: tr.order.riskPerTrade, v: [o.risk_pct != null ? `${o.risk_pct.toFixed(1)}%` : null, o.risk_usd != null ? money(o.risk_usd) : null].filter(Boolean).join(' · ') || DASH },
    { k: tr.order.size, v: [o.alloc_usd != null ? money(o.alloc_usd, 0) : null, o.position_pct != null ? `${o.position_pct.toFixed(1)}%` : null].filter(Boolean).join(' · ') || DASH },
    { k: tr.order.slippage, v: o.slippage_bps != null ? fill(tr.order.slippageValue, { bps: o.slippage_bps }) : DASH },
    { k: tr.order.maxCorr, v: num(trail.correlation?.max_corr) },
  ] : []

  const corrEntries = Object.entries(trail.correlation?.corr ?? {}).sort((a, b) => b[1] - a[1]).slice(0, 5)
  const outcomes = trail.outcomes

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_420px] gap-4 md:gap-6 items-start">
      <Panel title={options.title ?? fill(tr.title, { date: scanWhen })}>
        <ol className="flex flex-col">
          <Step
            n={1}
            title={tr.filter.title}
            right={tf ? (
              <span className="text-[13px] font-semibold" style={{ color: tf.passed === false ? theme.colors.warning : theme.colors.up }}>
                {tf.passed === false ? tr.filter.failed : fill(tr.filter.passed, { n: passedCount, total: tf.checks.length })}
              </span>
            ) : undefined}
          >
            {tf ? (
              <ul className="grid grid-cols-1 sm:grid-cols-2 gap-x-5 gap-y-2">
                {tf.checks.map((c) => (
                  <li key={c.key} className="flex items-center gap-2 text-[13px]" style={{ color: theme.colors.text }}>
                    {c.ok === true ? <Check size={14} strokeWidth={3} style={{ color: theme.colors.up }} aria-label={tr.filter.pass} />
                      : c.ok === false ? <X size={14} strokeWidth={3} style={{ color: theme.colors.warning }} aria-label={tr.filter.fail} />
                      : <Minus size={14} style={{ color: theme.colors.textSub }} aria-hidden="true" />}
                    {checkText(c, t)}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{tr.filter.notStored}</p>
            )}
          </Step>

          <Step
            n={2}
            title={tr.grok.title}
            right={g && !g.error ? (
              <span className="text-[13px]" style={{ color: theme.colors.textSub }}>
                {g.score != null && fill(tr.grok.sentiment, { score: Math.round(g.score) })}
                {g.score != null && ' · '}
                {fill(tr.grok.sources, { n: cites.length })}
              </span>
            ) : undefined}
          >
            {!g ? (
              <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{trail.ai_status === 'skipped' ? tr.routine.notCalled : tr.grok.none}</p>
            ) : g.error ? (
              <p className="text-[13px]" style={{ color: theme.colors.warning }}>{fill(tr.grok.error, { error: g.error })}</p>
            ) : (
              <>
                {g.summary && <p className="text-[13px] leading-relaxed" style={{ color: theme.colors.text }}>{g.summary}</p>}
                <div className="flex flex-col gap-1.5">
                  {g.red_flags.length === 0 ? (
                    <span className="text-[12px]" style={{ color: theme.colors.textSub }}>{tr.grok.redFlagsNone}</span>
                  ) : (
                    <div className="flex flex-col gap-1">
                      <span className="text-[12px]" style={{ color: theme.colors.textSub }}>{tr.grok.redFlags}</span>
                      <ul className="flex flex-col gap-1">
                        {g.red_flags.map((f, i) => (
                          <li key={i} className="text-[12px] flex gap-2 items-baseline" style={{ color: theme.colors.text }}>
                            {f.severity && (
                              <span className="uppercase text-[10px] font-bold px-1.5 py-0.5 rounded" style={{ color: theme.colors.warning, border: `1px solid ${theme.colors.warning}59` }}>
                                {f.severity}
                              </span>
                            )}
                            {f.url ? (
                              <a href={f.url} target="_blank" rel="noopener noreferrer" className="underline-offset-2 hover:underline" style={{ color: theme.colors.accent }}>
                                {f.text}<span className="sr-only"> {tr.grok.newTab}</span>
                              </a>
                            ) : f.text}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {cites.length > 0 && (
                    <ul className="flex flex-wrap gap-2">
                      {shownCites.map((u) => (
                        <li key={u}>
                          <a
                            href={u}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-block text-[12px] rounded-md px-2 py-1 hover:underline focus-visible:outline focus-visible:outline-2"
                            style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.accent, outlineColor: theme.colors.primary }}
                          >
                            {hostLabel(u)}<span className="sr-only"> {tr.grok.newTab}</span>
                          </a>
                        </li>
                      ))}
                      {cites.length > VISIBLE_CITATIONS && (
                        <li>
                          <button
                            type="button"
                            onClick={() => setShowAll((v) => !v)}
                            aria-expanded={showAll}
                            className="text-[12px] rounded-md px-2 py-1 focus-visible:outline focus-visible:outline-2"
                            style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.text, outlineColor: theme.colors.primary }}
                          >
                            {showAll ? tr.grok.less : fill(tr.grok.more, { n: cites.length - VISIBLE_CITATIONS })}
                          </button>
                        </li>
                      )}
                    </ul>
                  )}
                </div>
              </>
            )}
          </Step>

          <Step
            n={3}
            title={tr.routine.title}
            right={r ? <span className="text-[13px]" style={{ ...mono, color: verdictColor(r.signal) }}>{verdictLine(r.signal, r.confidence, r.p_win)}</span> : undefined}
          >
            {!r ? (
              <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{tr.routine.notCalled}</p>
            ) : r.reasoning ? (
              <p className="text-[13px] leading-relaxed whitespace-pre-line" style={{ color: theme.colors.text }}>{r.reasoning}</p>
            ) : dm ? (
              <p className="text-[12px]" style={{ color: theme.colors.textSub }}>{tr.routine.reasoningNotStored}</p>
            ) : null}
          </Step>

          <Step
            n={4}
            title={tr.decision.title}
            right={dm && dm.status !== 'unavailable' ? (
              <span className="text-[13px]" style={{ ...mono, color: verdictColor(dm.signal) }}>{verdictLine(dm.signal, dm.confidence, dm.p_win)}</span>
            ) : undefined}
          >
            {!dm ? (
              <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{r ? tr.decision.notEscalated : tr.routine.notCalled}</p>
            ) : dm.status === 'unavailable' ? (
              <p className="text-[13px]" style={{ color: theme.colors.warning }}>{tr.decision.unavailable}</p>
            ) : (
              <>
                <span className="text-[12px] font-semibold" style={{ color: dm.status === 'vetoed' ? theme.colors.warning : theme.colors.up }}>
                  {dm.status === 'vetoed' ? tr.decision.vetoed : tr.decision.confirmed}
                </span>
                {dm.reasoning && <p className="text-[13px] leading-relaxed whitespace-pre-line" style={{ color: theme.colors.text }}>{dm.reasoning}</p>}
              </>
            )}
          </Step>

          <Step
            n={5}
            last
            active={bought}
            title={options.orderTitle ?? tr.order.title}
            right={
              <span className="text-[13px] font-semibold" style={{ color: bought ? theme.colors.up : theme.colors.textSub }}>
                {options.orderStatus ? options.orderStatus.label : bought ? tr.order.bought : dec ? tr.order.skipped : tr.order.notEvaluated}
              </span>
            }
          >
            {dec && !bought && dec.reason && (
              <p className="text-[13px]" style={{ color: theme.colors.text }}>{formatReason(dec.reason, t)}</p>
            )}
            {o ? (
              <dl className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
                {orderTiles.map((x) => (
                  <div key={x.k} className="rounded-[10px] px-3 py-2.5 flex flex-col gap-1" style={{ backgroundColor: theme.colors.surfaceAlt }}>
                    <dt className="text-[11px]" style={{ color: theme.colors.textSub }}>{x.k}</dt>
                    <dd className="text-[14px] tabular-nums" style={{ ...mono, color: theme.colors.text }}>{x.v}</dd>
                  </div>
                ))}
              </dl>
            ) : (
              <p className="text-[12px]" style={{ color: theme.colors.textSub }}>{tr.order.none}</p>
            )}
          </Step>
        </ol>
      </Panel>

      <aside className="flex flex-col gap-4 md:gap-5 min-w-0">
        <Panel>
          <PriceChart
            symbol={trail.symbol}
            defaultRange="3M"
            title={tr.chart}
            levels={o ? { entry: o.fill ?? o.ref_price, stop: o.stop, target: o.target, labels: { entry: tr.entry, stop: tr.stop, target: tr.target } } : undefined}
          />
        </Panel>

        <Panel title={tr.fit.title}>
          {corrEntries.length === 0 && !trail.sector_exposure ? (
            <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{tr.fit.none}</p>
          ) : (
            <dl className="flex flex-col gap-2.5">
              {corrEntries.map(([sym, c]) => (
                <div key={sym} className="flex justify-between text-[13px]">
                  <dt style={{ color: theme.colors.textSub }}>{fill(tr.fit.corrWith, { symbol: sym })}</dt>
                  <dd className="tabular-nums" style={{ ...mono, color: theme.colors.text }}>{num(c)}</dd>
                </div>
              ))}
              {trail.sector_exposure && (
                <div className="flex justify-between text-[13px]">
                  <dt style={{ color: theme.colors.textSub }}>{fill(tr.fit.sectorHeld, { sector: trail.sector_exposure.sector })}</dt>
                  <dd className="tabular-nums" style={{ ...mono, color: theme.colors.text }}>{trail.sector_exposure.held} / {trail.sector_exposure.max}</dd>
                </div>
              )}
            </dl>
          )}
        </Panel>

        {showOutcomes && (
        <Panel title={tr.outcomes.title}>
          <dl className="grid grid-cols-3 gap-2.5">
            {(outcomes?.horizons ?? []).map((h) => (
              <div key={h.days} className="flex flex-col gap-1">
                <dt className="text-[12px]" style={{ color: theme.colors.textSub }}>{fill(tr.outcomes.days, { n: h.days })}</dt>
                <dd className="flex flex-col gap-0.5">
                  <span className="text-[13px]" style={{ color: theme.colors.textSub }}>{shortDate(h.filled_at ?? h.due_date, locale)}</span>
                  {h.excess_ret_frac != null ? (
                    <span className="text-[13px] tabular-nums" style={{ ...mono, color: h.excess_ret_frac >= 0 ? theme.colors.up : theme.colors.down }}>
                      {fill(tr.outcomes.vsSpy, { v: signedFracPct(h.excess_ret_frac, 1) })}
                    </span>
                  ) : (
                    <span className="text-[12px]" style={{ color: theme.colors.textSub }}>{tr.outcomes.pending}</span>
                  )}
                </dd>
              </div>
            ))}
          </dl>
          <p className="mt-2.5 text-[12px]" style={{ color: theme.colors.textSub }}>{tr.outcomes.note}</p>
        </Panel>
        )}
      </aside>
    </div>
  )
}
