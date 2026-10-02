'use client'

import { memo, useMemo, useState } from 'react'
import Link from 'next/link'
import { Layers } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { Panel } from '@/components/insights/Panel'
import { compactMoney } from '@/components/stock/StockChecks'
import { money, useMaskedMoney } from '@/components/holdings/format'
import { DASH, fill, shortDate } from '@/lib/insights'
import { PremiumHint } from '@/components/tracker/ui'
import type { StockFund, StockPosition } from '@/types/stock'

const pctText = (v: number | null | undefined, d = 2) =>
  v == null || !Number.isFinite(v) ? DASH : `${v.toFixed(d)}%`

/** ETF cards on the stock page Overview: about the fund, fee meter, asset
 *  mix, sectors and top holdings (GET /stocks/{symbol} "fund"). */
export function FundCards({ fund, currency, position }: {
  fund: StockFund
  currency: string
  position: StockPosition | null
}) {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start min-w-0">
      <div className="flex flex-col gap-4 min-w-0">
        <AboutFund fund={fund} currency={currency} />
        {fund.expense_ratio != null && <FeeMeter fee={fund.expense_ratio} position={position} />}
        {Object.keys(fund.asset_classes ?? {}).length > 0 && <AssetMix mix={fund.asset_classes} />}
        {fund.regions && Object.keys(fund.regions).length > 0 && <RegionsCard regions={fund.regions} />}
      </div>
      <div className="flex flex-col gap-4 min-w-0">
        {Object.keys(fund.sector_weights ?? {}).length > 0 && <Sectors weights={fund.sector_weights} />}
        {(fund.top_holdings ?? []).length > 0 && <TopHoldings fund={fund} />}
      </div>
    </div>
  )
}

const Row = memo(function Row({ label, value }: { label: string; value: string }) {
  const theme = useTheme()
  return (
    <div className="flex items-baseline justify-between gap-3 py-1.5 min-w-0" style={{ borderTop: `1px solid ${theme.colors.border}` }}>
      <dt className="text-[13px] shrink-0" style={{ color: theme.colors.textSub }}>{label}</dt>
      <dd className="text-[13.5px] font-medium text-right min-w-0 break-words tabular-nums" style={{ color: theme.colors.text }}>{value}</dd>
    </div>
  )
})

function AboutFund({ fund, currency }: { fund: StockFund; currency: string }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const tf = t.stock.fund
  const rows = [
    { label: tf.category, value: fund.category },
    { label: tf.family, value: fund.family },
    { label: tf.fee, value: fund.expense_ratio != null ? fill(tf.feeValue, { pct: pctText(fund.expense_ratio) }) : null },
    { label: tf.size, value: fund.aum != null ? compactMoney(fund.aum, currency) : null },
    { label: tf.holdings, value: fund.holdings_listed != null ? String(fund.holdings_listed) : null },
    { label: tf.top10, value: fund.top10_weight != null ? pctText(fund.top10_weight, 1) : null },
    { label: tf.since, value: fund.inception_date ? shortDate(fund.inception_date, locale, true) : null },
  ].filter((r): r is { label: string; value: string } => !!r.value)
  return (
    <Panel title={tf.aboutTitle}>
      <dl className="flex flex-col -mt-1.5">
        {rows.map((r) => <Row key={r.label} label={r.label} value={r.value} />)}
      </dl>
      {fund.fund_of_funds && (
        <p className="mt-3 text-[12.5px] flex items-start gap-2 rounded-xl p-2.5" style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.textSub }}>
          <Layers size={15} aria-hidden="true" className="shrink-0 mt-0.5" style={{ color: theme.colors.primary }} />{tf.fundOfFunds}
        </p>
      )}
    </Panel>
  )
}

/** 0% … 1%+ bar (green → amber → red) with a marker at the fee. */
function FeeMeter({ fee, position }: { fee: number; position: StockPosition | null }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const tf = t.stock.fund
  const mm = useMaskedMoney()
  const pos = Math.min(100, Math.max(0, (fee / 1) * 100))
  const home = position?.market_value_home != null
  const base = home ? position!.market_value_home : position?.market_value ?? null
  const ccy = home ? position!.home_currency : position?.currency ?? 'CAD'
  const yearly = base != null ? (base * fee) / 100 : null
  return (
    <Panel title={tf.feeTitle}>
      <div className="flex flex-col gap-2">
        <p className="text-[22px] font-bold tabular-nums" style={{ color: theme.colors.text }}>
          {pctText(fee)}<span className="text-[13px] font-medium ml-1" style={{ color: theme.colors.textSub }}>{tf.perYear}</span>
        </p>
        <div className="relative h-2.5 rounded-full" role="img" aria-label={fill(tf.feeAria, { pct: pctText(fee) })}
          style={{ background: `linear-gradient(90deg, ${theme.colors.up}, ${theme.colors.warning} 50%, ${theme.colors.down})` }}>
          <span className="absolute -top-1 w-1.5 h-[18px] rounded-full" aria-hidden="true"
            style={{ left: `calc(${pos}% - 3px)`, backgroundColor: theme.colors.text, boxShadow: `0 0 0 2px ${theme.colors.surface}` }} />
        </div>
        <div className="flex justify-between text-[11px] tabular-nums" style={{ color: theme.colors.textHint }}>
          <span>0%</span><span>0.5%</span><span>1%+</span>
        </div>
        <p className="text-[13px]" style={{ color: theme.colors.textSub }}>
          {yearly != null && base != null
            ? fill(tf.feeYours, { pct: pctText(fee), amount: mm(yearly, ccy, locale, 0), value: mm(base, ccy, locale, 0) })
            : tf.feeExplain}
        </p>
      </div>
    </Panel>
  )
}

function usePalette() {
  const theme = useTheme()
  const c = theme.colors
  return [c.primary, c.accent, c.warning, c.down, c.textSub, c.up, c.textHint]
}

function AssetMix({ mix }: { mix: Record<string, number> }) {
  const t = useI18nStore((s) => s.t)
  const tf = t.stock.fund
  return <MixCard title={tf.assetMix} mix={mix}
    label={(k) => (tf.assetClasses as Record<string, string>)[k] ?? k.replace(/Position$/, '')} />
}

/** Approximate regions (fund-of-funds holdings or a single-region index). */
function RegionsCard({ regions }: { regions: Record<string, number> }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const tf = t.stock.fund
  return <MixCard title={tf.regionsTitle} mix={regions}
    label={(k) => (tf.regions as Record<string, string>)[k] ?? k}
    note={<p className="mt-2 text-[12px]" style={{ color: theme.colors.textHint }}>{tf.regionsNote}</p>} />
}

/** Stacked bar + legend for a {key: PERCENT} breakdown. */
function MixCard({ title, mix, label, note }: {
  title: string; mix: Record<string, number>; label: (k: string) => string; note?: React.ReactNode
}) {
  const theme = useTheme()
  const palette = usePalette()
  const rows = useMemo(() => Object.entries(mix).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]), [mix])
  return (
    <Panel title={title}>
      <div className="flex h-3 rounded-full overflow-hidden" role="img"
        aria-label={rows.map(([k, v]) => `${label(k)} ${pctText(v, 1)}`).join(', ')}>
        {rows.map(([k, v], i) => (
          <span key={k} style={{ width: `${v}%`, backgroundColor: palette[i % palette.length] }} />
        ))}
      </div>
      <ul className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5">
        {rows.map(([k, v], i) => (
          <li key={k} className="flex items-center gap-2 text-[13px] min-w-0">
            <span className="w-2.5 h-2.5 rounded-sm shrink-0" aria-hidden="true" style={{ backgroundColor: palette[i % palette.length] }} />
            <span className="truncate" style={{ color: theme.colors.text }}>{label(k)}</span>
            <span className="ml-auto tabular-nums" style={{ color: theme.colors.textSub }}>{pctText(v, 1)}</span>
          </li>
        ))}
      </ul>
      {note}
    </Panel>
  )
}

function Sectors({ weights }: { weights: Record<string, number> }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const tf = t.stock.fund
  const rows = useMemo(() => Object.entries(weights).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]).slice(0, 8), [weights])
  const max = rows[0]?.[1] || 1
  const label = (k: string) => (tf.sectors as Record<string, string>)[k]
    ?? k.replace(/_/g, ' ').replace(/^\w/, (m) => m.toUpperCase())
  return (
    <Panel title={tf.sectorsTitle}>
      <ul className="flex flex-col gap-2">
        {rows.map(([k, v]) => (
          <li key={k} className="grid grid-cols-[minmax(0,9rem)_minmax(0,1fr)_3.5rem] items-center gap-2 text-[13px]">
            <span className="truncate" style={{ color: theme.colors.text }}>{label(k)}</span>
            <span className="h-2 rounded-full" style={{ backgroundColor: theme.colors.surfaceAlt }}>
              <span className="block h-full rounded-full" style={{ width: `${(v / max) * 100}%`, backgroundColor: theme.colors.primary }} />
            </span>
            <span className="text-right tabular-nums" style={{ color: theme.colors.textSub }}>{pctText(v, 1)}</span>
          </li>
        ))}
      </ul>
    </Panel>
  )
}

function TopHoldings({ fund }: { fund: StockFund }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const tf = t.stock.fund
  const [all, setAll] = useState(false)
  const items = fund.top_holdings ?? []
  const shown = all ? items : items.slice(0, 5)
  return (
    <Panel title={tf.topHoldings}>
      <ol className="flex flex-col">
        {shown.map((h, i) => {
          const inner = (
            <>
              <span className="w-5 text-[12px] tabular-nums" style={{ color: theme.colors.textHint }}>{i + 1}</span>
              <span className="min-w-0 flex-1">
                <span className="block font-mono text-[13px] font-semibold" style={{ color: theme.colors.text }}>{h.symbol ?? DASH}</span>
                <span className="block text-[12px] truncate" style={{ color: theme.colors.textSub }}>{h.name ?? ''}</span>
              </span>
              <span className="text-[13px] tabular-nums" style={{ color: theme.colors.text }}>{pctText(h.weight, 1)}</span>
            </>
          )
          return (
            <li key={`${h.symbol}-${i}`} style={{ borderTop: i ? `1px solid ${theme.colors.border}` : undefined }}>
              {h.symbol ? (
                <Link href={`/stocks/${encodeURIComponent(h.symbol)}`}
                  className="flex items-center gap-2 py-2 min-h-[44px] rounded hover:brightness-125 focus-visible:outline focus-visible:outline-2"
                  style={{ outlineColor: theme.colors.primary }}>
                  {inner}
                </Link>
              ) : <div className="flex items-center gap-2 py-2">{inner}</div>}
            </li>
          )
        })}
      </ol>
      {items.length > 5 && (
        <button type="button" onClick={() => setAll((a) => !a)}
          className="mt-1 min-h-[44px] px-1 text-[13px] font-medium rounded focus-visible:outline focus-visible:outline-2"
          style={{ color: theme.colors.primary, outlineColor: theme.colors.primary }}>
          {all ? tf.showFewer : fill(tf.showAll, { n: items.length })}
        </button>
      )}
    </Panel>
  )
}

/** Company / fund description, collapsed to 3 lines. */
export function AboutCard({ about }: { about: NonNullable<import('@/types/stock').StockAbout> }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const ta = t.stock.about
  const [open, setOpen] = useState(false)
  if (!about.description) return null
  const place = [about.city, about.state, about.country].filter(Boolean).join(', ')
  const site = about.website && /^https?:\/\//.test(about.website) ? about.website : null
  return (
    <Panel title={ta.title}>
      <p className={`text-[13.5px] leading-relaxed ${open ? '' : 'line-clamp-3'}`} style={{ color: theme.colors.text }}>{about.description}</p>
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}
        className="min-h-[44px] px-1 text-[13px] font-medium rounded focus-visible:outline focus-visible:outline-2"
        style={{ color: theme.colors.primary, outlineColor: theme.colors.primary }}>
        {open ? ta.less : ta.more}
      </button>
      {(place || about.employees || site) && (
        <p className="text-[12.5px] flex flex-wrap gap-x-3 gap-y-1" style={{ color: theme.colors.textSub }}>
          {place && <span>{place}</span>}
          {about.employees != null && <span>{fill(ta.employees, { n: about.employees.toLocaleString() })}</span>}
          {site && <a href={site} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2" style={{ color: theme.colors.primary }}>{site.replace(/^https?:\/\/(www\.)?/, '').replace(/\/$/, '')}</a>}
        </p>
      )}
    </Panel>
  )
}

/** Held dividend payers: the next payment for this position. */
export function NextPayoutCard({ amountPerShare, shares, currency, payDate, exDate, estimated }: {
  amountPerShare: number
  shares: number
  currency: string
  payDate: string | null
  exDate: string | null
  estimated: boolean
}) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const tn = t.stock.nextPayout
  const mm = useMaskedMoney()
  const parts = [
    payDate ? fill(tn.pays, { date: shortDate(payDate, locale, true) }) : null,
    exDate ? fill(payDate ? tn.ownBefore : tn.exOn, { date: shortDate(exDate, locale, true) }) : null,
    fill(tn.shares, { n: shares.toLocaleString() }),
  ].filter(Boolean)
  return (
    <Panel title={tn.title}>
      <p className="text-[22px] font-bold tabular-nums" style={{ color: theme.colors.up }}>≈ {mm(amountPerShare * shares, currency, locale)}</p>
      <p className="text-[13px] mt-1" style={{ color: theme.colors.textSub }}>
        {parts.join(' · ')}{estimated ? ` (${tn.estimated})` : ''}
      </p>
      <p className="text-[12px] mt-1" style={{ color: theme.colors.textHint }}>{fill(tn.perShare, { amount: money(amountPerShare, currency, locale, 4) })}</p>
    </Panel>
  )
}


/** Similar funds compared (Premium, feature.similar_funds). Free gets
 *  similar_locked=true from the server → a Premium hint instead. */
export function SimilarFunds({ items, locked }: { items: import('@/types/stock').SimilarFund[] | null | undefined; locked?: boolean }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const ts = t.stock.similar
  if (locked) return <Panel title={ts.title}><PremiumHint body={ts.premium} /></Panel>
  if (!items || items.length === 0) return null
  const cols = [
    { key: 'expense_ratio' as const, label: ts.fee },
    { key: 'yield' as const, label: ts.yield },
    { key: 'return_1y_pct' as const, label: ts.return1y },
    { key: 'return_5y_pct' as const, label: ts.return5y },
  ].filter((c) => items.some((i) => i[c.key] != null))
  return (
    <Panel title={ts.title}>
      <p className="text-[12px] -mt-1 mb-2" style={{ color: theme.colors.textHint }}>{ts.note}</p>
      <div className="overflow-x-auto">
        <table className="w-full text-[13px] min-w-[360px]">
          <thead>
            <tr style={{ color: theme.colors.textSub }}>
              <th scope="col" className="text-left font-medium py-1.5">{ts.fund}</th>
              {cols.map((c) => <th key={c.key} scope="col" className="text-right font-medium py-1.5">{c.label}</th>)}
            </tr>
          </thead>
          <tbody>
            {items.map((f) => (
              <tr key={f.symbol} style={{ borderTop: `1px solid ${theme.colors.border}`, backgroundColor: f.current ? theme.colors.primary + '14' : undefined }}>
                <th scope="row" className="text-left font-normal py-2 pr-2">
                  <Link href={`/stocks/${encodeURIComponent(f.symbol)}`} className="font-mono font-semibold rounded focus-visible:outline focus-visible:outline-2"
                    style={{ color: theme.colors.text, outlineColor: theme.colors.primary }}>{f.symbol}</Link>
                  {f.current && <span className="ml-1.5 text-[11px] font-semibold" style={{ color: theme.colors.primary }}>{ts.thisFund}</span>}
                  {f.name && <span className="block text-[12px] truncate max-w-[220px]" style={{ color: theme.colors.textSub }}>{f.name}</span>}
                </th>
                {cols.map((c) => <td key={c.key} className="text-right tabular-nums py-2" style={{ color: theme.colors.text }}>{pctText(f[c.key] ?? null, c.key === 'expense_ratio' ? 2 : 1)}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  )
}
