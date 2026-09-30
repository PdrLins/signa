'use client'

import { memo, useId, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Download, FileUp, Undo2 } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useToast } from '@/hooks/useToast'
import { transactionsApi } from '@/lib/api'
import { fill, shortDate } from '@/lib/insights'
import { money, num } from '@/components/holdings/format'
import { trackerErrorText } from '@/lib/trackerErrors'
import { SectionCard, useButtonStyles, useFieldStyle } from '@/components/profile/ui'
import type { ImportDryRun, ImportOptions, ImportResult, ImportRow, RowError } from '@/types/transactions'
import type en from '@/lib/i18n/en.json'

type DateFormat = NonNullable<ImportOptions['date_format']>
const PREVIEW_ROWS = 5
const ERROR_ROWS = 50

function rowErrorText(e: RowError, t: typeof en): string {
  return (t.tracker.errors as Record<string, string>)[e.code] ?? e.message
}

const ErrorLine = memo(function ErrorLine({ line, errors }: { line: number; errors: RowError[] }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  return (
    <li className="text-[13px] min-w-0 break-words" style={{ color: theme.colors.text }}>
      <span className="font-semibold tabular-nums" style={{ color: theme.colors.down }}>{fill(t.transactionsPage.import.line, { line })}</span>
      {' · '}{errors.map((e) => `${e.field}: ${rowErrorText(e, t)}`).join(' · ')}
    </li>
  )
})

const PreviewLine = memo(function PreviewLine({ row }: { row: ImportRow }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const d = row.data
  if (!d) return null
  return (
    <li className="text-[13px] flex flex-wrap gap-x-2 tabular-nums min-w-0" style={{ color: theme.colors.textSub }}>
      <span>{shortDate(d.trade_date ?? null, locale, true)}</span>
      <span style={{ color: theme.colors.text }}>{d.type ? t.transactionsPage.types[d.type] : ''}</span>
      {d.symbol && <span className="font-mono" style={{ color: theme.colors.text }}>{d.symbol}</span>}
      {d.quantity != null && <span>{num(d.quantity, locale)}</span>}
      {d.amount != null && <span>{money(d.amount, d.currency, locale)}</span>}
      {d.account_name && <span>{d.account_name}</span>}
    </li>
  )
})

/** CSV import: template → upload → dry-run preview with per-row errors →
 *  confirm (optionally skipping bad rows) → success with "Undo import". */
export function CsvImport({ onClose }: { onClose: () => void }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const ti = t.transactionsPage.import
  const toast = useToast()
  const qc = useQueryClient()
  const f = useFieldStyle()
  const btn = useButtonStyles()
  const ids = { file: useId(), fmt: useId(), create: useId(), skip: useId() }
  const fileRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [dateFormat, setDateFormat] = useState<DateFormat>('auto')
  const [createMissing, setCreateMissing] = useState(false)
  const [skipErrors, setSkipErrors] = useState(false)
  const [phase, setPhase] = useState<'pick' | 'checking' | 'preview' | 'importing' | 'done' | 'undoing'>('pick')
  const [dry, setDry] = useState<ImportDryRun | null>(null)
  const [result, setResult] = useState<ImportResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [templateBusy, setTemplateBusy] = useState(false)

  const opts: ImportOptions = { date_format: dateFormat, create_missing_accounts: createMissing }

  const downloadTemplate = async () => {
    setTemplateBusy(true)
    try {
      const csv = await transactionsApi.templateCsv()
      const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
      const a = document.createElement('a')
      a.href = url
      a.download = 'signa-transactions-template.csv'
      document.body.appendChild(a)
      a.click()
      a.remove()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (e) {
      toast.show(trackerErrorText(e, t), 'error')
    } finally {
      setTemplateBusy(false)
    }
  }

  const check = async () => {
    if (!file) return
    setError(null)
    setPhase('checking')
    try {
      const res = await transactionsApi.import(file, true, opts)
      setDry(res as ImportDryRun)
      setSkipErrors(false)
      setPhase('preview')
    } catch (e) {
      setError(trackerErrorText(e, t))
      setPhase('pick')
    }
  }

  const confirm = async () => {
    if (!file) return
    setError(null)
    setPhase('importing')
    try {
      const res = await transactionsApi.import(file, false, { ...opts, skip_errors: skipErrors })
      setResult(res as ImportResult)
      setPhase('done')
      qc.invalidateQueries({ queryKey: ['transactions'] })
      qc.invalidateQueries({ queryKey: ['accounts'] })
      toast.show(fill(ti.success, { n: (res as ImportResult).imported }), 'success')
    } catch (e) {
      setError(trackerErrorText(e, t))
      setPhase('preview')
    }
  }

  const undo = async () => {
    if (!result) return
    setPhase('undoing')
    try {
      const res = await transactionsApi.undoImport(result.import_batch_id)
      toast.show(fill(ti.undone, { n: res.deleted }), 'success')
      qc.invalidateQueries({ queryKey: ['transactions'] })
      reset()
    } catch (e) {
      toast.show(trackerErrorText(e, t), 'error')
      setPhase('done')
    }
  }

  const reset = () => {
    setFile(null)
    setDry(null)
    setResult(null)
    setError(null)
    setSkipErrors(false)
    setPhase('pick')
    if (fileRef.current) fileRef.current.value = ''
  }

  const s = dry?.summary
  const okRows = useMemo(() => (dry?.rows ?? []).filter((r) => r.status === 'ok').slice(0, PREVIEW_ROWS), [dry])
  const errRows = useMemo(() => (dry?.rows ?? []).filter((r) => r.status === 'error'), [dry])
  const canImport = !!s && s.valid > 0 && (s.invalid === 0 || skipErrors)
  const checkbox = 'flex items-center gap-3 min-h-[44px] text-[13px] cursor-pointer'

  return (
    <SectionCard title={ti.title} subtitle={ti.body}>
      {(phase === 'pick' || phase === 'checking') && (
        <div className="flex flex-col gap-3">
          <button type="button" onClick={downloadTemplate} disabled={templateBusy}
            className={`${btn.secondary.className} self-start`} style={btn.secondary.style}>
            <Download size={16} aria-hidden="true" />{ti.template}
          </button>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <label htmlFor={ids.file} className={f.label} style={{ color: f.labelColor }}>
              {ti.choose}
              <input id={ids.file} ref={fileRef} type="file" accept=".csv,text/csv,text/plain"
                onChange={(e) => { setFile(e.target.files?.[0] ?? null); setError(null) }}
                className={`${f.input} py-2`} style={f.style} />
            </label>
            <label htmlFor={ids.fmt} className={f.label} style={{ color: f.labelColor }}>
              {ti.dateFormat}
              <select id={ids.fmt} value={dateFormat} onChange={(e) => setDateFormat(e.target.value as DateFormat)} className={f.input} style={f.style}>
                {(['auto', 'dmy', 'mdy'] as DateFormat[]).map((d) => <option key={d} value={d}>{ti.dateFormats[d]}</option>)}
              </select>
            </label>
          </div>
          <label htmlFor={ids.create} className={checkbox} style={{ color: theme.colors.text }}>
            <input id={ids.create} type="checkbox" checked={createMissing} onChange={(e) => setCreateMissing(e.target.checked)}
              className="w-5 h-5 shrink-0" style={{ accentColor: theme.colors.primary }} />
            {ti.createMissing}
          </label>
          {error && <p role="alert" className="text-[13px]" style={{ color: theme.colors.down }}>{error}</p>}
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={check} disabled={!file || phase === 'checking'} className={btn.primary.className} style={btn.primary.style}>
              <FileUp size={16} aria-hidden="true" />{phase === 'checking' ? ti.checking : ti.check}
            </button>
            <button type="button" onClick={onClose} className={btn.secondary.className} style={btn.secondary.style}>{ti.cancel}</button>
          </div>
        </div>
      )}

      {(phase === 'preview' || phase === 'importing') && s && (
        <div className="flex flex-col gap-3">
          <p className="text-[14px] font-medium" role="status" style={{ color: theme.colors.text }}>
            {fill(ti.summary, { valid: s.valid, rows: s.rows, invalid: s.invalid })}
          </p>
          {s.date_range && (
            <p className="text-[13px]" style={{ color: theme.colors.textSub }}>
              {fill(ti.range, { from: shortDate(s.date_range.from, locale, true), to: shortDate(s.date_range.to, locale, true) })}
            </p>
          )}
          {s.accounts_to_create.length > 0 && (
            <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{fill(ti.newAccounts, { names: s.accounts_to_create.join(', ') })}</p>
          )}
          {okRows.length > 0 && (
            <div>
              <h3 className="text-[13px] font-semibold mb-1" style={{ color: theme.colors.text }}>{ti.preview}</h3>
              <ul className="flex flex-col gap-1">
                {okRows.map((r) => <PreviewLine key={r.line} row={r} />)}
              </ul>
              {s.valid > okRows.length && (
                <p className="text-[12px] mt-1" style={{ color: theme.colors.textHint }}>{fill(ti.moreRows, { n: s.valid - okRows.length })}</p>
              )}
            </div>
          )}
          {errRows.length > 0 && (
            <div className="rounded-xl p-3" style={{ border: `1px solid ${theme.colors.down}` }}>
              <h3 className="text-[13px] font-semibold mb-1" style={{ color: theme.colors.text }}>{ti.rowsWithErrors}</h3>
              <ul className="flex flex-col gap-1 max-h-64 overflow-y-auto">
                {errRows.slice(0, ERROR_ROWS).map((r) => <ErrorLine key={r.line} line={r.line} errors={r.errors} />)}
              </ul>
              {errRows.length > ERROR_ROWS && (
                <p className="text-[12px] mt-1" style={{ color: theme.colors.textHint }}>{fill(ti.moreRows, { n: errRows.length - ERROR_ROWS })}</p>
              )}
            </div>
          )}
          {s.invalid > 0 && s.valid > 0 && (
            <label htmlFor={ids.skip} className={checkbox} style={{ color: theme.colors.text }}>
              <input id={ids.skip} type="checkbox" checked={skipErrors} onChange={(e) => setSkipErrors(e.target.checked)}
                className="w-5 h-5 shrink-0" style={{ accentColor: theme.colors.primary }} />
              {ti.skipErrors}
            </label>
          )}
          {error && <p role="alert" className="text-[13px]" style={{ color: theme.colors.down }}>{error}</p>}
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={confirm} disabled={!canImport || phase === 'importing'} className={btn.primary.className} style={btn.primary.style}>
              {phase === 'importing' ? ti.importing : fill(ti.confirm, { n: s.valid })}
            </button>
            <button type="button" onClick={reset} disabled={phase === 'importing'} className={btn.secondary.className} style={btn.secondary.style}>
              {ti.another}
            </button>
          </div>
        </div>
      )}

      {(phase === 'done' || phase === 'undoing') && result && (
        <div className="flex flex-col gap-2" role="status">
          <p className="text-[14px] font-medium flex items-center gap-2" style={{ color: theme.colors.text }}>
            <CheckCircle2 size={18} aria-hidden="true" style={{ color: theme.colors.up }} />
            {fill(ti.success, { n: result.imported })}
          </p>
          {result.skipped > 0 && <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{fill(ti.skipped, { n: result.skipped })}</p>}
          {result.accounts_created.length > 0 && (
            <p className="text-[13px]" style={{ color: theme.colors.textSub }}>
              {fill(ti.accountsCreated, { names: result.accounts_created.map((a) => a.name).join(', ') })}
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={undo} disabled={phase === 'undoing'} className={btn.danger.className}
              style={{ ...btn.danger.style, border: `1px solid ${theme.colors.border}` }}>
              <Undo2 size={16} aria-hidden="true" />{phase === 'undoing' ? ti.undoing : ti.undo}
            </button>
            <button type="button" onClick={reset} disabled={phase === 'undoing'} className={btn.secondary.className} style={btn.secondary.style}>
              {ti.another}
            </button>
            <button type="button" onClick={onClose} disabled={phase === 'undoing'} className={btn.secondary.className} style={btn.secondary.style}>
              {t.tracker.close}
            </button>
          </div>
        </div>
      )}
    </SectionCard>
  )
}
