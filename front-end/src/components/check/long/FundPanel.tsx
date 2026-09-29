'use client'

import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { Panel, mono } from '@/components/insights/Panel'
import { DASH, fill } from '@/lib/insights'
import type { FundInfo } from '@/types/check'
import { compactMoney, fixed, pct } from './format'

function MixBars({ title, data, names }: { title: string; data: Record<string, number>; names: Record<string, string> }) {
  const theme = useTheme()
  const entries = Object.entries(data).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1])
  if (entries.length === 0) return null
  const max = Math.max(...entries.map(([, v]) => v))
  return (
    <div className="flex flex-col gap-2 min-w-0">
      <h3 className="text-[13px] font-semibold" style={{ color: theme.colors.text }}>{title}</h3>
      <ul className="flex flex-col gap-1.5">
        {entries.map(([k, v]) => (
          <li key={k} className="flex flex-col gap-1 min-w-0">
            <div className="flex items-baseline justify-between gap-2 text-[12px]">
              <span className="truncate" style={{ color: theme.colors.text }}>{names[k] ?? k.replace(/_/g, ' ')}</span>
              <span className="tabular-nums shrink-0" style={{ ...mono, color: theme.colors.textSub }}>{pct(v)}</span>
            </div>
            <span className="h-1.5 rounded-full overflow-hidden" aria-hidden="true" style={{ backgroundColor: theme.colors.surfaceAlt }}>
              <span className="block h-full rounded-full" style={{ width: `${(v / max) * 100}%`, backgroundColor: theme.colors.primary }} />
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** ETF facts: cost, size, yield, holdings (as reported — a fund of funds
 *  shows its underlying ETFs), sector and asset-class mix. */
export function FundPanel({ fund: f, currency }: { fund: FundInfo; currency: string | null }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const tl = t.check.long

  const facts: { k: string; v: string }[] = [
    { k: tl.expenseRatio, v: f.expense_ratio != null ? fill(tl.expenseRatioValue, { v: f.expense_ratio.toFixed(2) }) : DASH },
    { k: tl.aum, v: compactMoney(f.aum, currency) },
    { k: tl.yield, v: pct(f.yield, 2) },
    { k: tl.holdingsPe, v: fixed(f.pe, 1) },
    { k: tl.holdingsPb, v: fixed(f.pb, 1) },
    { k: tl.turnover, v: pct(f.turnover, 0) },
  ]
  const shown = f.top_holdings.slice(0, 10)

  return (
    <Panel title={tl.fundTitle} subtitle={[f.family, f.category].filter(Boolean).join(' · ') || undefined}>
      <div className="flex flex-col gap-5">
        <dl className="grid grid-cols-2 sm:grid-cols-3 gap-2.5">
          {facts.map((x) => (
            <div key={x.k} className="rounded-[10px] px-3 py-2.5 flex flex-col gap-1 min-w-0" style={{ backgroundColor: theme.colors.surfaceAlt }}>
              <dt className="text-[11px]" style={{ color: theme.colors.textSub }}>{x.k}</dt>
              <dd className="text-[14px] tabular-nums break-words" style={{ ...mono, color: theme.colors.text }}>{x.v}</dd>
            </div>
          ))}
        </dl>

        <div className="flex flex-col gap-2 min-w-0">
          <h3 className="text-[13px] font-semibold" style={{ color: theme.colors.text }}>{tl.topHoldings}</h3>
          {shown.length === 0 ? (
            <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{tl.noHoldings}</p>
          ) : (
            <>
              {f.top10_weight != null && (
                <p className="text-[12px]" style={{ color: theme.colors.textSub }}>
                  {fill(tl.topHoldingsSub, { n: shown.length, w: f.top10_weight.toFixed(1) })}
                  {f.fund_of_funds && <> · {tl.fundOfFunds}</>}
                </p>
              )}
              <ol className="flex flex-col">
                {shown.map((h) => (
                  <li key={h.symbol} className="flex items-center justify-between gap-3 py-2 min-w-0" style={{ borderBottom: `1px solid ${theme.colors.border}` }}>
                    <span className="flex flex-col min-w-0">
                      <span className="text-[13px] font-medium" style={{ ...mono, color: theme.colors.text }}>{h.symbol}</span>
                      {h.name && <span className="text-[12px] truncate" style={{ color: theme.colors.textSub }}>{h.name}</span>}
                    </span>
                    <span className="text-[13px] tabular-nums shrink-0" style={{ ...mono, color: theme.colors.text }}>{pct(h.weight, 1)}</span>
                  </li>
                ))}
              </ol>
            </>
          )}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
          <MixBars title={tl.sectors} data={f.sector_weights} names={tl.sectorNames as Record<string, string>} />
          <MixBars title={tl.assetMix} data={f.asset_classes} names={tl.assetClassNames as Record<string, string>} />
        </div>
      </div>
    </Panel>
  )
}
