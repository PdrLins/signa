'use client'

import { Suspense, useEffect, useId, useRef, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { Search } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useStockCheck } from '@/hooks/useStockCheck'
import { ProgressBar } from '@/components/ui/ProgressBar'
import { Panel } from '@/components/insights/Panel'
import { CheckResultView, useVerdictStyle } from '@/components/check/CheckResultView'
import { LongResultView } from '@/components/check/long/LongResultView'
import { useLongVerdictStyle } from '@/components/check/long/format'
import {
  checkHref, clearRecent, loadMode, loadRecent, parseMode, saveMode, saveRecent, type RecentCheck,
} from '@/lib/check'
import { fill, shortDate } from '@/lib/insights'
import { isLongResult, type CheckMode, type CheckResult, type CheckVerdict, type LongVerdict } from '@/types/check'

const PHASES: Record<CheckMode, string[]> = {
  short: ['resolving', 'market_data', 'filter', 'sentiment', 'synthesis', 'decision', 'risk'],
  long: ['resolving', 'history', 'benchmark', 'fundamentals', 'sentiment', 'assessment'],
}
const MODES: CheckMode[] = ['short', 'long']

export default function CheckPage() {
  return (
    <Suspense fallback={null}>
      <CheckPageInner />
    </Suspense>
  )
}

function CheckPageInner() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const tc = t.check
  const router = useRouter()
  const params = useSearchParams()
  const inputId = useId()
  const helpId = useId()
  const modeHelpId = useId()
  const shortStyle = useVerdictStyle()
  const longStyle = useLongVerdictStyle()
  const [value, setValue] = useState('')
  const [mode, setMode] = useState<CheckMode>('short')
  const [recent, setRecent] = useState<RecentCheck[]>([])
  const autoRan = useRef<string | null>(null)
  const headingRef = useRef<HTMLHeadingElement>(null)

  const check = useStockCheck((r) => setRecent(saveRecent(r)))

  useEffect(() => setRecent(loadRecent()), [])

  const paramTicker = params.get('ticker')?.trim().toUpperCase() ?? ''
  const paramMode = parseMode(params.get('mode'))

  // Mode: ?mode= wins; a ?ticker= link without a mode is a short check (the
  // Today box default); otherwise the last choice saved in this browser.
  useEffect(() => {
    if (paramMode) setMode(paramMode)
    else if (!paramTicker) setMode(loadMode())
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const run = (ticker: string, force = false, m: CheckMode = mode) => {
    const v = ticker.trim().toUpperCase()
    if (!v) return
    setValue(v)
    setMode(m)
    autoRan.current = `${v}|${m}`
    if (paramTicker !== v || (paramMode ?? 'short') !== m) router.replace(checkHref(v, m))
    check.start(v, force, m)
  }

  const chooseMode = (m: CheckMode) => {
    setMode(m)
    saveMode(m)
    // Keep the URL in sync without starting a new (counted) check.
    if (paramTicker) {
      autoRan.current = `${paramTicker}|${m}`
      router.replace(checkHref(paramTicker, m))
    }
  }

  // /check?ticker=XYZ[&mode=long] (e.g. from the Today search box) starts automatically.
  useEffect(() => {
    const m = paramMode ?? 'short'
    const key = `${paramTicker}|${m}`
    if (paramTicker && autoRan.current !== key) {
      autoRan.current = key
      setValue(paramTicker)
      setMode(m)
      check.start(paramTicker, false, m)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paramTicker, paramMode])

  // Move focus to the verdict when it arrives (screen readers + keyboard).
  useEffect(() => {
    if (check.result) headingRef.current?.focus()
  }, [check.result])

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!check.running) run(value)
  }

  const job = check.job
  const runMode: CheckMode = check.mode
  const phaseNames = (runMode === 'long' ? tc.longPhases : tc.phases) as Record<string, string>
  const phases = PHASES[runMode]
  const phase = job?.phase ?? 'resolving'
  const phaseLabel = phaseNames[phase] ?? phase
  const recentStyle = (r: RecentCheck) =>
    r.mode === 'long' ? longStyle(r.verdict as LongVerdict) : shortStyle(r.verdict as CheckVerdict)
  const recentVerdict = (r: RecentCheck) =>
    ((r.mode === 'long' ? tc.long.verdict : tc.verdict) as Record<string, string>)[r.verdict] ?? r.verdict
  const pct = job?.pct ?? 0
  const shownSymbol = job?.symbol ?? check.ticker ?? value
  const err = check.error
  const errText = err
    ? fill((tc.errors as Record<string, string>)[err.code] ?? err.message ?? tc.errors.internal, { ticker: check.ticker ?? value })
    : null

  return (
    <div className="flex flex-col gap-4 md:gap-6">
      <header className="flex flex-col gap-1.5">
        <h1 className="text-[26px] md:text-[30px] font-semibold tracking-tight" style={{ color: theme.colors.text }}>{tc.title}</h1>
        <p className="text-[13px] md:text-sm max-w-2xl" style={{ color: theme.colors.textSub }}>{mode === 'long' ? tc.subtitleLong : tc.subtitle}</p>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_300px] gap-4 md:gap-6 items-start">
        <Panel>
          <form role="search" onSubmit={onSubmit} className="flex flex-col gap-2" aria-label={tc.title}>
            <fieldset className="flex flex-col gap-1.5 mb-2 min-w-0" aria-describedby={modeHelpId}>
              <legend className="text-[13px] font-medium mb-1.5" style={{ color: theme.colors.text }}>{tc.modeLabel}</legend>
              <div
                className="grid grid-cols-2 gap-1 p-1 rounded-[12px]"
                style={{ backgroundColor: theme.colors.surfaceAlt, border: `1px solid ${theme.colors.border}` }}
              >
                {MODES.map((m) => {
                  const on = mode === m
                  return (
                    <label
                      key={m}
                      className="relative flex items-center justify-center min-h-11 px-2 rounded-[9px] text-[13px] sm:text-sm font-medium text-center cursor-pointer select-none has-[:focus-visible]:outline has-[:focus-visible]:outline-2"
                      style={{
                        backgroundColor: on ? theme.colors.surface : 'transparent',
                        color: on ? theme.colors.primary : theme.colors.textSub,
                        boxShadow: on ? (theme.isDark ? '0 1px 4px rgba(0,0,0,0.4)' : '0 1px 4px rgba(0,0,0,0.08)') : undefined,
                        outlineColor: theme.colors.primary,
                        opacity: check.running ? 0.6 : 1,
                      }}
                    >
                      <input
                        type="radio"
                        name="check-mode"
                        value={m}
                        checked={on}
                        disabled={check.running}
                        onChange={() => chooseMode(m)}
                        className="sr-only"
                      />
                      {tc.modes[m]}
                    </label>
                  )
                })}
              </div>
              <p id={modeHelpId} className="text-[12px]" style={{ color: theme.colors.textSub }}>{tc.modeHelp[mode]}</p>
            </fieldset>
            <label htmlFor={inputId} className="text-[13px] font-medium" style={{ color: theme.colors.text }}>{tc.label}</label>
            <div className="flex gap-2">
              <input
                id={inputId}
                type="text"
                autoCapitalize="characters"
                autoComplete="off"
                spellCheck={false}
                maxLength={20}
                value={value}
                onChange={(e) => setValue(e.target.value)}
                placeholder={tc.placeholder}
                aria-describedby={helpId}
                className="flex-1 min-w-0 h-11 rounded-[10px] px-3 text-[15px] outline-none focus-visible:outline focus-visible:outline-2"
                style={{
                  backgroundColor: theme.colors.surfaceAlt, color: theme.colors.text,
                  border: `1px solid ${theme.colors.border}`, outlineColor: theme.colors.primary, fontFamily: 'var(--font-mono)',
                }}
              />
              <button
                type="submit"
                disabled={check.running || !value.trim()}
                className="inline-flex items-center gap-2 h-11 px-4 rounded-[10px] text-sm font-medium disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
                style={{ backgroundColor: theme.colors.primary, color: theme.colors.surface, outlineColor: theme.colors.primary }}
              >
                <Search size={16} aria-hidden="true" />
                {check.running ? tc.checking : tc.submit}
              </button>
            </div>
            <p id={helpId} className="text-[12px]" style={{ color: theme.colors.textSub }}>
              {tc.inputHelp}
              {job?.remaining_today != null && <> · {fill(tc.remaining, { n: job.remaining_today })}</>}
            </p>
          </form>
        </Panel>

        <Panel
          title={tc.recent}
          right={recent.length > 0 ? (
            <button
              type="button"
              onClick={() => { clearRecent(); setRecent([]) }}
              className="inline-flex items-center min-h-11 px-2 -my-2 text-[12px] hover:underline focus-visible:outline focus-visible:outline-2 rounded"
              style={{ color: theme.colors.textSub, outlineColor: theme.colors.primary }}
            >
              {tc.clearRecent}
            </button>
          ) : undefined}
        >
          {recent.length === 0 ? (
            <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{tc.recentEmpty}</p>
          ) : (
            <ul className="flex flex-col gap-1">
              {recent.map((r) => {
                const vs = recentStyle(r)
                return (
                  <li key={`${r.symbol}|${r.mode}`}>
                    <button
                      type="button"
                      onClick={() => run(r.symbol, false, r.mode)}
                      disabled={check.running}
                      aria-label={`${fill(tc.recentOpen, { symbol: r.symbol })} · ${tc.modes[r.mode]}`}
                      className="w-full min-h-11 flex items-center justify-between gap-2 rounded-lg px-2 py-1.5 text-left disabled:opacity-60 hover:opacity-80 focus-visible:outline focus-visible:outline-2"
                      style={{ outlineColor: theme.colors.primary }}
                    >
                      <span className="flex items-center gap-2 min-w-0">
                        <vs.Icon size={14} aria-hidden="true" style={{ color: vs.color }} className="shrink-0" />
                        <span className="text-[13px] font-medium" style={{ color: theme.colors.text, fontFamily: 'var(--font-mono)' }}>{r.symbol}</span>
                        <span
                          className="text-[10.5px] font-medium px-1.5 py-px rounded shrink-0"
                          style={{ color: theme.colors.textSub, border: `1px solid ${theme.colors.border}` }}
                        >
                          {tc.modeShort[r.mode]}
                        </span>
                        <span className="text-[12px] truncate" style={{ color: vs.color }}>{recentVerdict(r)}</span>
                      </span>
                      <span className="text-[11px] shrink-0" style={{ color: theme.colors.textSub }}>{shortDate(r.checked_at, locale)}</span>
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </Panel>
      </div>

      {/* Progress — announced politely to screen readers */}
      <div aria-live="polite" role="status" className="min-h-0">
        {check.running && (
          <Panel title={fill(tc.progressTitle, { symbol: shownSymbol })}>
            <div className="flex flex-col gap-3">
              <div
                role="progressbar"
                aria-label={tc.progressLabel}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={pct}
                aria-valuetext={`${pct}% · ${phaseLabel}`}
              >
                <ProgressBar value={pct} height={6} />
              </div>
              <p className="text-[13px]" style={{ color: theme.colors.text }}>{phaseLabel} · {pct}%</p>
              <ol className="flex flex-wrap gap-x-4 gap-y-1">
                {phases.map((p) => {
                  const idx = phases.indexOf(phase)
                  const i = phases.indexOf(p)
                  const state = i < idx ? 'done' : i === idx ? 'current' : 'todo'
                  return (
                    <li
                      key={p}
                      aria-current={state === 'current' ? 'step' : undefined}
                      className="text-[12px]"
                      style={{ color: state === 'todo' ? theme.colors.textHint : state === 'current' ? theme.colors.primary : theme.colors.textSub, fontWeight: state === 'current' ? 600 : 400 }}
                    >
                      {phaseNames[p]}
                    </li>
                  )
                })}
              </ol>
            </div>
          </Panel>
        )}
      </div>

      {errText && !check.running && (
        <div
          role="alert"
          className="rounded-2xl p-5 flex flex-wrap items-center justify-between gap-3"
          style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.border}`, borderLeft: `4px solid ${theme.colors.warning}` }}
        >
          <p className="text-sm" style={{ color: theme.colors.text }}>{errText}</p>
          {err && !['invalid_ticker', 'not_found', 'daily_limit'].includes(err.code) && check.ticker && (
            <button
              type="button"
              onClick={() => run(check.ticker ?? value, false, check.mode)}
              className="min-h-11 px-3 rounded-lg text-[13px] font-medium focus-visible:outline focus-visible:outline-2"
              style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.primary, outlineColor: theme.colors.primary }}
            >
              {tc.tryAgain}
            </button>
          )}
        </div>
      )}

      {check.result && !check.running && (isLongResult(check.result) ? (
        <LongResultView
          ref={headingRef}
          result={check.result}
          onRecheck={() => run(check.result?.symbol ?? value, true, 'long')}
          recheckDisabled={check.running}
        />
      ) : (
        <CheckResultView
          ref={headingRef}
          result={check.result as CheckResult}
          onRecheck={() => run(check.result?.symbol ?? value, true, 'short')}
          recheckDisabled={check.running}
        />
      ))}
    </div>
  )
}
