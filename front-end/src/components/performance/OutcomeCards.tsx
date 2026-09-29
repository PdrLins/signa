'use client'

import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { Panel, NotEnough } from '@/components/insights/Panel'
import { fill, gateLabel, signedFracPct, num } from '@/lib/insights'
import type { PerformanceInsights, StatSummary } from '@/types/insights'

/** Horizontal bar around a zero line; `mean` is a decimal fraction. */
function ZeroBar({ mean, scale, color }: { mean: number; scale: number; color: string }) {
  const theme = useTheme()
  const w = Math.min(50, (Math.abs(mean) / scale) * 50)
  return (
    <div className="relative h-[22px]" aria-hidden="true">
      <div className="absolute left-1/2 top-0 bottom-0 w-px" style={{ backgroundColor: theme.colors.textSub + '66' }} />
      <div
        className="absolute top-[5px] h-3 rounded-[3px]"
        style={{ left: mean >= 0 ? '50%' : `${50 - w}%`, width: `${Math.max(w, 0.5)}%`, backgroundColor: color }}
      />
    </div>
  )
}

export function CohortsCard({ data }: { data: PerformanceInsights }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const c = t.performance.cohorts
  const need = data.threshold
  const labels: Record<string, string> = { entered: c.entered, vetoed: c.vetoed, rejected: c.rejected, ai_not_called: c.ai_not_called }
  const scale = Math.max(0.01, ...data.cohorts.filter((r) => r.sufficient && r.mean != null).map((r) => Math.abs(r.mean!)))
  const entered = data.cohorts.find((r) => r.key === 'entered')

  return (
    <Panel title={c.title} subtitle={fill(c.sub, { h: data.horizon })}>
      <ul className="flex flex-col gap-3">
        {data.cohorts.map((r) => (
          <li key={r.key} className="grid grid-cols-[minmax(0,150px)_minmax(0,1fr)_auto] md:grid-cols-[170px_minmax(0,1fr)_70px_64px] gap-3 items-center">
            <span className="text-[13px]" style={{ color: theme.colors.text }}>{labels[r.key] ?? r.key}</span>
            {r.sufficient && r.mean != null ? (
              <>
                <ZeroBar mean={r.mean} scale={scale} color={r.mean >= 0 ? theme.colors.up : theme.colors.down} />
                <span className="text-[13px] text-right tabular-nums" style={{ color: theme.colors.text, fontFamily: 'var(--font-mono)' }} title={r.ci ? fill(c.ciNote, { lo: signedFracPct(r.ci[0]), hi: signedFracPct(r.ci[1]) }) : undefined}>
                  {signedFracPct(r.mean)}
                </span>
                <span className="hidden md:inline text-[12px] text-right tabular-nums" style={{ color: theme.colors.textSub, fontFamily: 'var(--font-mono)' }}>n={r.n}</span>
              </>
            ) : (
              <span className="col-span-2 md:col-span-3 justify-self-end md:justify-self-start">
                <NotEnough n={r.n} needed={need} label={t.performance.notEnough} />
              </span>
            )}
          </li>
        ))}
      </ul>
      {entered && !entered.sufficient && (
        <p className="mt-3 text-[12px]" style={{ color: theme.colors.warning }}>{fill(c.note, { n: entered.n, needed: need })}</p>
      )}
    </Panel>
  )
}

export function CalibrationCard({ data }: { data: PerformanceInsights }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const k = t.performance.calibration
  const cal = data.calibration
  const need = data.threshold
  const ready = cal.n >= need && cal.buckets.length > 0
  // plot area: p_win 0.4..1.0 on both axes
  const lo = 0.4, hi = 1.0
  const X = (v: number) => 30 + ((Math.min(hi, Math.max(lo, v)) - lo) / (hi - lo)) * 220
  const Y = (v: number) => 190 - ((Math.min(hi, Math.max(lo, v)) - lo) / (hi - lo)) * 180
  const maxN = Math.max(1, ...cal.buckets.map((b) => b.n))

  return (
    <Panel title={k.title} subtitle={fill(k.sub, { h: cal.horizon })}>
      {!ready ? (
        <div className="flex flex-col gap-2 items-start">
          <NotEnough n={cal.n} needed={need} label={t.performance.notEnough} />
          <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{cal.n === 0 ? k.empty : fill(k.brierPending, { needed: need, n: cal.n })}</p>
        </div>
      ) : (
        <div className="flex flex-col sm:flex-row gap-5 sm:items-center">
          <svg viewBox="0 0 260 220" className="w-full max-w-[260px] h-auto shrink-0" role="img" aria-label={k.chartLabel}>
            <rect x="30" y="10" width="220" height="180" fill="none" stroke={theme.colors.border} />
            <line x1={X(lo)} y1={Y(lo)} x2={X(hi)} y2={Y(hi)} stroke={theme.colors.textSub} strokeDasharray="4 4" />
            {cal.buckets.map((b) => (
              <circle key={b.bucket} cx={X(b.mean_p_win)} cy={Y(b.win_rate)} r={4 + 6 * Math.sqrt(b.n / maxN)} fill={theme.colors.primary} stroke={theme.colors.surface} strokeWidth="2">
                <title>{fill(k.bucketRow, { bucket: b.bucket, pred: num(b.mean_p_win), actual: `${Math.round(b.win_rate * 100)}%`, n: b.n })}</title>
              </circle>
            ))}
            <text x="30" y="210" fill={theme.colors.textSub} fontSize="11" fontFamily="var(--font-mono)">0.4</text>
            <text x="232" y="210" fill={theme.colors.textSub} fontSize="11" fontFamily="var(--font-mono)">1.0</text>
            <text x="0" y="194" fill={theme.colors.textSub} fontSize="11" fontFamily="var(--font-mono)">40%</text>
            <text x="0" y="16" fill={theme.colors.textSub} fontSize="11" fontFamily="var(--font-mono)">100%</text>
          </svg>
          <div className="flex flex-col gap-2.5 text-[13px] leading-relaxed" style={{ color: theme.colors.text }}>
            <span>{k.explain1}</span>
            <span>{k.explain2}</span>
            {cal.brier != null && (
              <span style={{ color: theme.colors.textSub }}>{fill(k.brier, { brier: num(cal.brier, 3), base: num(cal.brier_base_rate, 3) })}</span>
            )}
            {cal.hidden_buckets > 0 && <span style={{ color: theme.colors.textSub }}>{fill(k.hidden, { n: cal.hidden_buckets })}</span>}
            {/* table view of the dots */}
            <table className="sr-only">
              <caption>{k.chartLabel}</caption>
              <thead><tr><th>p_win</th><th>{k.axisPred}</th><th>{k.axisActual}</th><th>n</th></tr></thead>
              <tbody>{cal.buckets.map((b) => <tr key={b.bucket}><td>{b.bucket}</td><td>{num(b.mean_p_win)}</td><td>{Math.round(b.win_rate * 100)}%</td><td>{b.n}</td></tr>)}</tbody>
            </table>
          </div>
        </div>
      )}
    </Panel>
  )
}

export function OpusCard({ data }: { data: PerformanceInsights }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const o = t.performance.opus
  const need = data.threshold
  const ov = data.overturn
  const tile = (label: string, s: StatSummary, highlight: boolean) => (
    <div className="rounded-xl p-4 flex flex-col gap-1.5" style={{ backgroundColor: theme.colors.surfaceAlt }}>
      <span className="text-[13px]" style={{ color: theme.colors.textSub }}>{label}</span>
      {s.sufficient && s.mean != null ? (
        <>
          <span className="text-[22px] tabular-nums" style={{ color: highlight ? theme.colors.up : theme.colors.text, fontFamily: 'var(--font-mono)' }}>{signedFracPct(s.mean, 1)}</span>
          <span className="text-[12px]" style={{ color: theme.colors.textSub }}>
            {fill(o.vsSpyAfter, { h: data.horizon })} · <span style={{ fontFamily: 'var(--font-mono)' }}>n={s.n}</span>
          </span>
        </>
      ) : (
        <span className="mt-1"><NotEnough n={s.n} needed={need} label={t.performance.notEnough} /></span>
      )}
    </div>
  )
  const decided = ov.confirmed.sufficient && ov.vetoed.sufficient
  const diff = ov.diff != null ? signedFracPct(Math.abs(ov.diff)) : ''
  return (
    <Panel title={o.title} subtitle={o.sub}>
      <div className="grid grid-cols-2 gap-3">
        {tile(o.confirmed, ov.confirmed, true)}
        {tile(o.vetoed, ov.vetoed, false)}
      </div>
      <p className="mt-3 text-[12px]" style={{ color: decided ? theme.colors.textSub : theme.colors.warning }}>
        {!decided ? fill(o.note, { needed: need })
          : ov.direction === 'veto_helps' ? fill(o.helps, { diff })
          : ov.direction === 'veto_costs' ? fill(o.costs, { diff })
          : o.noDiff}
      </p>
    </Panel>
  )
}

export function CodexCard({ data }: { data: PerformanceInsights }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const k = t.performance.codex
  const need = data.threshold
  const cx = data.codex
  if (!cx) return null
  const rows: { key: string; label: string; s: StatSummary; highlight: boolean }[] = [
    { key: 'agree', label: k.agree, s: cx.agree, highlight: true },
    { key: 'disagree', label: k.disagree, s: cx.disagree, highlight: false },
  ]
  const decided = cx.agree.sufficient && cx.disagree.sufficient
  const diff = cx.diff != null ? signedFracPct(Math.abs(cx.diff)) : ''
  return (
    <Panel title={k.title} subtitle={k.sub}>
      {cx.reviewed === 0 ? (
        <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{k.none}</p>
      ) : (
        <table className="w-full text-left">
          <thead>
            <tr className="grid grid-cols-[minmax(0,1fr)_40px_minmax(72px,auto)] gap-2.5 py-2 text-[12px]" style={{ color: theme.colors.textSub, borderBottom: `1px solid ${theme.colors.border}` }}>
              <th scope="col" className="font-normal">{t.performance.skip.colReason}</th>
              <th scope="col" className="font-normal text-right">{t.performance.skip.colN}</th>
              <th scope="col" className="font-normal text-right">{fill(t.performance.skip.colRet, { h: data.horizon })}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key} className="grid grid-cols-[minmax(0,1fr)_40px_minmax(72px,auto)] gap-2.5 py-2.5 items-center" style={{ borderBottom: `1px solid ${theme.colors.border}` }}>
                <td className="text-[13px]" style={{ color: theme.colors.text }}>{r.label}</td>
                <td className="text-[13px] text-right tabular-nums" style={{ color: theme.colors.text, fontFamily: 'var(--font-mono)' }}>{r.s.n}</td>
                <td className="text-[13px] text-right tabular-nums" style={{ color: r.s.sufficient && r.s.mean != null && r.highlight ? theme.colors.up : theme.colors.text, fontFamily: 'var(--font-mono)' }}>
                  {r.s.sufficient && r.s.mean != null ? signedFracPct(r.s.mean, 1) : <NotEnough n={r.s.n} needed={need} label={t.performance.notEnough} />}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="mt-3 text-[12px]" style={{ color: decided ? theme.colors.textSub : theme.colors.warning }}>
        {!decided ? fill(k.note, { needed: need })
          : cx.direction === 'codex_helps' ? fill(k.helps, { diff })
          : cx.direction === 'codex_costs' ? fill(k.costs, { diff })
          : k.noDiff}
      </p>
    </Panel>
  )
}

export function SkipRulesCard({ data }: { data: PerformanceInsights }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const k = t.performance.skip
  const need = data.threshold
  const verdictColor = (v: string) => v === 'protective' ? theme.colors.up : v === 'costing' ? theme.colors.down : v === 'inconclusive' ? theme.colors.warning : theme.colors.textSub
  const verdictText: Record<string, string> = { costing: k.costing, protective: k.protective, inconclusive: k.inconclusive, insufficient: k.insufficient }
  const cols = 'grid-cols-[minmax(0,1fr)_36px_70px_minmax(92px,auto)]'
  return (
    <Panel padded={false} title={k.title} subtitle={k.sub}>
      {data.skip_reasons.length === 0 ? (
        <p className="px-5 md:px-6 text-sm" style={{ color: theme.colors.textSub }}>{k.empty}</p>
      ) : (
        <table className="w-full text-left">
          <thead>
            <tr className={`grid ${cols} gap-2.5 px-5 md:px-6 py-2 text-[12px]`} style={{ color: theme.colors.textSub, borderTop: `1px solid ${theme.colors.border}`, borderBottom: `1px solid ${theme.colors.border}` }}>
              <th scope="col" className="font-normal">{k.colReason}</th>
              <th scope="col" className="font-normal text-right">{k.colN}</th>
              <th scope="col" className="font-normal text-right">{fill(k.colRet, { h: data.horizon })}</th>
              <th scope="col" className="font-normal">{k.colVerdict}</th>
            </tr>
          </thead>
          <tbody>
            {data.skip_reasons.map((g) => (
              <tr key={g.reason} className={`grid ${cols} gap-2.5 px-5 md:px-6 py-2.5 items-center`} style={{ borderBottom: `1px solid ${theme.colors.border}` }}>
                <td className="text-[13px]" style={{ color: theme.colors.text }}>{gateLabel(g.reason, t)}</td>
                <td className="text-[13px] text-right tabular-nums" style={{ color: theme.colors.text, fontFamily: 'var(--font-mono)' }}>{g.n}</td>
                <td className="text-[13px] text-right tabular-nums" style={{ color: theme.colors.text, fontFamily: 'var(--font-mono)' }}>
                  {g.sufficient && g.mean != null ? signedFracPct(g.mean, 1) : '—'}
                </td>
                <td className="text-[12px] font-semibold" style={{ color: verdictColor(g.verdict) }}>
                  {g.verdict === 'insufficient' ? <span className="font-normal">{fill(t.performance.notEnough, { n: g.n, needed: need })}</span> : verdictText[g.verdict] ?? g.verdict}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  )
}
