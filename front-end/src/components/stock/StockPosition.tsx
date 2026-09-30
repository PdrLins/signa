'use client'

import { memo, useEffect, useId, useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { usePrivacyStore } from '@/store/privacyStore'
import { DASH, fill, signedPct } from '@/lib/insights'
import { MASK, money, num } from '@/components/holdings/format'
import { pct } from '@/components/check/long/format'
import { Panel } from '@/components/insights/Panel'
import { HideAmountsButton, useSignColor } from '@/components/tracker/ui'
import type { StockPL, StockPosition as Position } from '@/types/stock'

/** Share-of-portfolio ring (SVG donut, theme colours). */
const WeightRing = memo(function WeightRing({ value, label }: { value: number | null; label: string }) {
  const theme = useTheme()
  const r = 26
  const c = 2 * Math.PI * r
  const v = value === null ? 0 : Math.max(0, Math.min(100, value))
  return (
    <div className="flex items-center gap-3 min-w-0">
      <svg width="64" height="64" viewBox="0 0 64 64" role="img" aria-label={label} className="shrink-0">
        <circle cx="32" cy="32" r={r} fill="none" stroke={theme.colors.surfaceAlt} strokeWidth="8" />
        <circle cx="32" cy="32" r={r} fill="none" stroke={theme.colors.primary} strokeWidth="8" strokeLinecap="round"
          strokeDasharray={`${(v / 100) * c} ${c}`} transform="rotate(-90 32 32)" />
        <text x="32" y="36" textAnchor="middle" fontSize="12" fontWeight="700" fill={theme.colors.text}>
          {value === null ? DASH : `${value < 10 ? value.toFixed(1) : Math.round(value)}%`}
        </text>
      </svg>
    </div>
  )
})

/** "Your position" on the stock page: shares, average cost, value, share of
 *  the portfolio (ring), today / open P/L, dividends received, total gain,
 *  and a collapsible per-account breakdown. Money respects the hide-amounts
 *  toggle; share counts and percentages stay visible. */
export function StockPosition({ position: p, symbol }: { position: Position; symbol: string }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const tp = t.stock.position
  const hidden = usePrivacyStore((s) => s.hidden)
  const load = usePrivacyStore((s) => s.load)
  useEffect(() => { load() }, [load])
  const signColor = useSignColor()
  const [open, setOpen] = useState(false)
  const listId = useId()

  const m = (v: number | null | undefined, ccy = p.currency) => (hidden ? MASK : money(v, ccy, locale))
  const homeDiffers = p.home_currency !== p.currency
  const withHome = (v: number | null, home: number | null) =>
    hidden ? MASK : homeDiffers && home !== null ? `${money(v, p.currency, locale)} · ${money(home, p.home_currency, locale)}` : money(v, p.currency, locale)
  const pl = (x: StockPL) => (
    <span className="flex flex-col">
      <span style={{ color: signColor(x.abs) }}>{hidden ? MASK : x.abs === null ? DASH : `${x.abs >= 0 ? '+' : ''}${money(x.abs, p.currency, locale)}`}</span>
      <span className="text-[12px] font-medium" style={{ color: signColor(x.pct) }}>{signedPct(x.pct)}</span>
    </span>
  )

  const cell = 'rounded-xl p-3 min-w-0 flex flex-col gap-0.5'
  const lbl = 'text-[12px]'
  const val = 'text-[15.5px] font-semibold tabular-nums break-words'
  const cellStyle = { backgroundColor: theme.colors.surfaceAlt }

  return (
    <Panel title={tp.title} right={<HideAmountsButton />}>
      <div className="flex flex-col gap-3 min-w-0">
        <div className="flex items-center gap-4 min-w-0">
          <WeightRing value={p.weight_pct} label={fill(tp.shareAria, { pct: p.weight_pct === null ? DASH : pct(p.weight_pct) })} />
          <div className="min-w-0">
            <p className="text-[12px]" style={{ color: theme.colors.textSub }}>{tp.value}</p>
            <p className="text-[22px] font-bold tabular-nums leading-tight break-words" style={{ color: theme.colors.text }}>
              {m(p.market_value)}
            </p>
            {homeDiffers && p.market_value_home !== null && (
              <p className="text-[12.5px] tabular-nums" style={{ color: theme.colors.textSub }}>{m(p.market_value_home, p.home_currency)}</p>
            )}
            <p className="text-[12px]" style={{ color: theme.colors.textHint }}>{tp.share}</p>
          </div>
        </div>
        <dl className="grid grid-cols-2 md:grid-cols-3 gap-2">
          <div className={cell} style={cellStyle}>
            <dt className={lbl} style={{ color: theme.colors.textSub }}>{tp.shares}</dt>
            <dd className={val} style={{ color: theme.colors.text }}>{num(p.shares, locale, 6)}</dd>
          </div>
          <div className={cell} style={cellStyle}>
            <dt className={lbl} style={{ color: theme.colors.textSub }}>{tp.avgCost}</dt>
            <dd className={val} style={{ color: theme.colors.text }}>{money(p.avg_cost, p.currency, locale, p.avg_cost !== null && p.avg_cost < 1 ? 4 : 2)}</dd>
          </div>
          <div className={cell} style={cellStyle}>
            <dt className={lbl} style={{ color: theme.colors.textSub }}>{tp.today}</dt>
            <dd className={val}>{pl(p.today_pl)}</dd>
          </div>
          <div className={cell} style={cellStyle}>
            <dt className={lbl} style={{ color: theme.colors.textSub }}>{tp.open}</dt>
            <dd className={val}>{pl(p.open_pl)}</dd>
          </div>
          <div className={cell} style={cellStyle}>
            <dt className={lbl} style={{ color: theme.colors.textSub }}>{tp.dividends}</dt>
            <dd className={val} style={{ color: p.dividends_received === null ? theme.colors.textHint : theme.colors.text }}>
              {p.dividends_received === null ? DASH : m(p.dividends_received)}
            </dd>
            {p.dividends_received === null && <span className="text-[11.5px]" style={{ color: theme.colors.textHint }}>{tp.dividendsNone}</span>}
          </div>
          <div className={cell} style={cellStyle}>
            <dt className={lbl} style={{ color: theme.colors.textSub }} title={tp.totalHint}>{tp.total}</dt>
            <dd className={val}>{pl(p.total_gain)}</dd>
          </div>
        </dl>
        {p.price_source === 'last_close' && <p className="text-[12px]" style={{ color: theme.colors.textHint }}>{tp.lastClose}</p>}
        {p.per_account.length > 1 ? (
          <div className="flex flex-col gap-1">
            <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-controls={listId}
              className="self-start min-h-[44px] px-2 -mx-2 rounded-lg text-[13px] font-medium inline-flex items-center gap-1.5 focus-visible:outline focus-visible:outline-2"
              style={{ color: theme.colors.primary, outlineColor: theme.colors.primary }}>
              <ChevronDown size={15} aria-hidden="true" className={open ? 'rotate-180 transition-transform' : 'transition-transform'} />
              {open ? tp.hideAccounts : fill(tp.showAccounts, { n: p.per_account.length })}
            </button>
            <ul id={listId} hidden={!open} aria-label={`${tp.accounts} · ${symbol}`} className="flex flex-col">
              {p.per_account.map((a) => (
                <li key={a.account_id ?? 'none'} className="flex items-center justify-between gap-3 py-2 text-[13px] min-w-0"
                  style={{ borderTop: `1px solid ${theme.colors.border}` }}>
                  <span className="min-w-0 flex flex-col">
                    <span className="font-medium truncate" style={{ color: theme.colors.text }}>{a.account_name ?? tp.noAccount}</span>
                    <span className="text-[12px] tabular-nums" style={{ color: theme.colors.textSub }}>
                      {fill(tp.sharesIn, { shares: num(a.shares, locale, 6) })} · {money(a.avg_cost, p.currency, locale)}
                    </span>
                  </span>
                  <span className="tabular-nums font-semibold shrink-0" style={{ color: theme.colors.text }}>{withHome(a.value, a.value_home)}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : p.per_account[0]?.account_name ? (
          <p className="text-[12.5px]" style={{ color: theme.colors.textSub }}>{tp.accounts}: {p.per_account[0].account_name}</p>
        ) : null}
      </div>
    </Panel>
  )
}
