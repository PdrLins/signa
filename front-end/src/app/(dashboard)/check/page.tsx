'use client'

import { Suspense, useCallback, useEffect, useId, useRef, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { Search } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useStockCheck } from '@/hooks/useStockCheck'
import { useStockCompare } from '@/hooks/useStockCompare'
import { ProgressBar } from '@/components/ui/ProgressBar'
import { Panel } from '@/components/insights/Panel'
import { CheckResultView, useVerdictStyle } from '@/components/check/CheckResultView'
import { LongResultView } from '@/components/check/long/LongResultView'
import { SymbolCombobox, resolveRawEntry } from '@/components/check/SymbolCombobox'
import { useLongVerdictStyle } from '@/components/check/long/format'
import { CompareForm } from '@/components/check/compare/CompareForm'
import { CompareProgress } from '@/components/check/compare/CompareProgress'
import { CompareResults } from '@/components/check/compare/CompareResults'
import {
  checkHref, clearRecent, compareHref, COMPARE_MIN, loadCompareSet, loadMode, loadRecent, parseCompareParam,
  parseMode, saveCompareSet, saveMode, saveRecent, type RecentCheck,
} from '@/lib/check'
import { fill, shortDate } from '@/lib/insights'
import { isLongResult, type CheckMode, type CheckResult, type CheckVerdict, type LongVerdict } from '@/types/check'
import type { SymbolMatch } from '@/types/symbols'

const PHASES: Record<CheckMode, string[]> = {
  short: ['resolving', 'market_data', 'filter', 'sentiment', 'synthesis', 'decision', 'risk'],
  long: ['resolving', 'history', 'benchmark', 'fundamentals', 'sentiment', 'assessment'],
}
const MODES: CheckMode[] = ['short', 'long']
type Kind = 'single' | 'compare'
const KINDS: Kind[] = ['single', 'compare']

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
  const kindHelpId = useId()
  const shortStyle = useVerdictStyle()
  const longStyle = useLongVerdictStyle()
  const [value, setValue] = useState('')
  const [mode, setMode] = useState<CheckMode>('short')
  const [recent, setRecent] = useState<RecentCheck[]>([])
  const [kind, setKind] = useState<Kind>('single')
  const [compareValues, setCompareValues] = useState<string[]>(['', ''])
  const autoRan = useRef<string | null>(null)
  const autoCompared = useRef<string | null>(null)
  const headingRef = useRef<HTMLHeadingElement>(null)
  const compareHeadingRef = useRef<HTMLHeadingElement>(null)

  const check = useStockCheck((r) => setRecent(saveRecent(r)))
  const compare = useStockCompare()
  const busy = check.running || compare.running

  useEffect(() => setRecent(loadRecent()), [])

  const paramTicker = params.get('ticker')?.trim().toUpperCase() ?? ''
  const paramMode = parseMode(params.get('mode'))
  const paramCompareRaw = params.get('compare') ?? ''
  const paramCompare = parseCompareParam(paramCompareRaw)

  // Mode: ?mode= wins; a ?ticker= link without a mode is a short check (the
  // Today box default); otherwise the last choice saved in this browser.
  useEffect(() => {
    if (paramMode) setMode(paramMode)
    else if (!paramTicker && !paramCompare.length) setMode(loadMode())
    if (paramCompare.length) setKind('compare')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const run = (ticker: string, force = false, m: CheckMode = mode) => {
    const v = ticker.trim().toUpperCase()
    if (!v) return
    setValue(v)
    setMode(m)
    setKind('single')
    autoRan.current = `${v}|${m}`
    if (paramTicker !== v || (paramMode ?? 'short') !== m) router.replace(checkHref(v, m))
    check.start(v, force, m)
  }

  const runCompare = (tickers: string[], force = false, m: CheckMode = mode) => {
    const list = tickers.map((x) => x.trim().toUpperCase()).filter(Boolean)
    if (list.length < COMPARE_MIN) return
    setKind('compare')
    setMode(m)
    setCompareValues(list)
    saveCompareSet(list, m)
    const href = compareHref(list, m)
    autoCompared.current = `${list.join(',')}|${m}`
    if (paramCompare.join(',') !== list.join(',') || (paramMode ?? 'short') !== m) router.replace(href)
    compare.start(list, force, m)
  }

  const chooseKind = (k: Kind) => {
    setKind(k)
    // Drop the other view's URL so a reload doesn't start it again.
    if ((k === 'single' && paramCompareRaw) || (k === 'compare' && paramTicker)) router.replace('/check')
    if (k === 'compare') {
      const saved = loadCompareSet()
      if (saved && compareValues.every((v) => !v.trim())) {
        setCompareValues(saved.tickers.length >= COMPARE_MIN ? saved.tickers : [...saved.tickers, ''])
      }
    }
  }

  const chooseMode = (m: CheckMode) => {
    setMode(m)
    saveMode(m)
    // Keep the URL in sync without starting a new (counted) check.
    if (kind === 'compare') {
      if (paramCompare.length) {
        autoCompared.current = `${paramCompare.join(',')}|${m}`
        router.replace(compareHref(paramCompare, m))
      }
    } else if (paramTicker) {
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
      setKind('single')
      setValue(paramTicker)
      setMode(m)
      check.start(paramTicker, false, m)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paramTicker, paramMode])

  // /check?compare=AAPL,MSFT[&mode=long] starts a comparison automatically.
  useEffect(() => {
    const m = paramMode ?? 'short'
    if (paramCompare.length < COMPARE_MIN) return
    const key = `${paramCompare.join(',')}|${m}`
    if (autoCompared.current !== key) {
      autoCompared.current = key
      setKind('compare')
      setMode(m)
      setCompareValues(paramCompare)
      saveCompareSet(paramCompare, m)
      compare.start(paramCompare, false, m)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paramCompareRaw, paramMode])

  // Move focus to the verdict when it arrives (screen readers + keyboard).
  useEffect(() => {
    if (check.result) headingRef.current?.focus()
  }, [check.result])

  const compareDone = compare.job?.status === 'done' ? compare.job : null
  useEffect(() => {
    if (compareDone) compareHeadingRef.current?.focus()
  }, [compareDone])

  const suggestions = useRef<SymbolMatch[]>([])
  const onResults = useCallback((r: SymbolMatch[]) => { suggestions.current = r }, [])

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!busy) run(resolveRawEntry(value, suggestions.current))
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

  const cErr = compare.error
  const cExtra = (cErr?.extra ?? {}) as Record<string, unknown>
  const listOf = (v: unknown) => (Array.isArray(v) ? v.map(String).join(', ') : null)
  const compareErrText = cErr
    ? fill(
      (tc.compare.errors as Record<string, string>)[cErr.code]
        ?? (tc.errors as Record<string, string>)[cErr.code]
        ?? cErr.message ?? tc.errors.internal,
      {
        ticker: listOf(cExtra.inputs) ?? (typeof cExtra.input === 'string' ? cExtra.input : compare.tickers.join(', ')),
        symbols: listOf(cExtra.symbols),
        inputs: listOf(cExtra.inputs),
        needed: typeof cExtra.needed === 'number' ? cExtra.needed : null,
        remaining: typeof cExtra.remaining === 'number' ? cExtra.remaining : null,
      },
    )
    : null

  return (
    <div className="flex flex-col gap-4 md:gap-6">
      <header className="flex flex-col gap-1.5">
        <h1 className="text-[26px] md:text-[30px] font-semibold tracking-tight" style={{ color: theme.colors.text }}>{tc.title}</h1>
        <p className="text-[13px] md:text-sm max-w-2xl" style={{ color: theme.colors.textSub }}>{mode === 'long' ? tc.subtitleLong : tc.subtitle}</p>
      </header>

      <div className={`grid grid-cols-1 gap-4 md:gap-6 items-start ${kind === 'single' ? 'lg:grid-cols-[minmax(0,1fr)_300px]' : ''}`}>
        <Panel>
          <div className="flex flex-col gap-2">
            <fieldset className="flex flex-col gap-1.5 mb-2 min-w-0" aria-describedby={kindHelpId}>
              <legend className="text-[13px] font-medium mb-1.5" style={{ color: theme.colors.text }}>{tc.compare.kindLabel}</legend>
              <div
                className="grid grid-cols-2 gap-1 p-1 rounded-[12px]"
                style={{ backgroundColor: theme.colors.surfaceAlt, border: `1px solid ${theme.colors.border}` }}
              >
                {KINDS.map((k) => {
                  const on = kind === k
                  return (
                    <label
                      key={k}
                      className="relative flex items-center justify-center min-h-11 px-2 rounded-[9px] text-[13px] sm:text-sm font-medium text-center cursor-pointer select-none has-[:focus-visible]:outline has-[:focus-visible]:outline-2"
                      style={{
                        backgroundColor: on ? theme.colors.surface : 'transparent',
                        color: on ? theme.colors.primary : theme.colors.textSub,
                        boxShadow: on ? (theme.isDark ? '0 1px 4px rgba(0,0,0,0.4)' : '0 1px 4px rgba(0,0,0,0.08)') : undefined,
                        outlineColor: theme.colors.primary,
                        opacity: busy ? 0.6 : 1,
                      }}
                    >
                      <input
                        type="radio"
                        name="check-kind"
                        value={k}
                        checked={on}
                        disabled={busy}
                        onChange={() => chooseKind(k)}
                        className="sr-only"
                      />
                      {tc.compare.kinds[k]}
                    </label>
                  )
                })}
              </div>
              <p id={kindHelpId} className="text-[12px]" style={{ color: theme.colors.textSub }}>{tc.compare.kindHelp[kind]}</p>
            </fieldset>
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
                        opacity: busy ? 0.6 : 1,
                      }}
                    >
                      <input
                        type="radio"
                        name="check-mode"
                        value={m}
                        checked={on}
                        disabled={busy}
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
            {kind === 'compare' ? (
              <CompareForm
                values={compareValues}
                onChange={setCompareValues}
                onSubmit={(list) => { if (!busy) runCompare(list) }}
                running={busy}
                remaining={compare.job?.remaining_today ?? job?.remaining_today ?? null}
              />
            ) : (
          <form role="search" onSubmit={onSubmit} className="flex flex-col gap-2" aria-label={tc.title}>
            <label htmlFor={inputId} className="text-[13px] font-medium" style={{ color: theme.colors.text }}>{tc.label}</label>
            <div className="relative flex gap-2">
              <SymbolCombobox
                id={inputId}
                value={value}
                onChange={setValue}
                onPick={(m) => { if (!busy) run(m.symbol) }}
                onResults={onResults}
                placeholder={tc.placeholder}
                describedBy={helpId}
                className="flex-1 min-w-0 h-11 rounded-[10px] px-3 text-[15px] outline-none focus-visible:outline focus-visible:outline-2"
                style={{
                  backgroundColor: theme.colors.surfaceAlt, color: theme.colors.text,
                  border: `1px solid ${theme.colors.border}`, outlineColor: theme.colors.primary,
                }}
              />
              <button
                type="submit"
                disabled={busy || !value.trim()}
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
            )}
          </div>
        </Panel>

        {kind === 'single' && (
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
                      disabled={busy}
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
        )}
      </div>

      {kind === 'compare' && compare.running && (
        <CompareProgress job={compare.job} tickers={compare.tickers} mode={compare.mode} />
      )}

      {kind === 'compare' && compareErrText && !compare.running && (
        <div
          role="alert"
          className="rounded-2xl p-5 flex flex-wrap items-center justify-between gap-3"
          style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.border}`, borderLeft: `4px solid ${theme.colors.warning}` }}
        >
          <p className="text-sm" style={{ color: theme.colors.text }}>{compareErrText}</p>
          {compare.error && !['invalid_ticker', 'compare_unknown', 'compare_duplicate', 'compare_count', 'daily_limit'].includes(compare.error.code) && compare.tickers.length >= COMPARE_MIN && (
            <button
              type="button"
              onClick={() => runCompare(compare.tickers, false, compare.mode)}
              className="min-h-11 px-3 rounded-lg text-[13px] font-medium focus-visible:outline focus-visible:outline-2"
              style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.primary, outlineColor: theme.colors.primary }}
            >
              {tc.tryAgain}
            </button>
          )}
        </div>
      )}

      {kind === 'compare' && compareDone && !compare.running && (
        <CompareResults
          ref={compareHeadingRef}
          job={compareDone}
          onRerun={() => runCompare(compareDone.symbols, true, compareDone.mode)}
          rerunDisabled={busy}
        />
      )}

      {/* Progress — announced politely to screen readers */}
      <div aria-live="polite" role="status" className="min-h-0">
        {kind === 'single' && check.running && (
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

      {kind === 'single' && errText && !check.running && (
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

      {kind === 'single' && check.result && !check.running && (isLongResult(check.result) ? (
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
