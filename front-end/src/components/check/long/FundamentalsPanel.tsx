'use client'

import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { Panel, mono } from '@/components/insights/Panel'
import { DASH, fill } from '@/lib/insights'
import type { StockFundamentals } from '@/types/check'
import { compactMoney, fixed, pct, spct } from './format'

/** Company fundamentals grouped as valuation / quality / growth / dividend
 *  / analyst estimates. Missing values render as "—". */
export function FundamentalsPanel({ data: f, currency }: { data: StockFundamentals; currency: string | null }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const tl = t.check.long
  const trend = f.growth.trend
  const span = trend.length >= 2 ? { from: trend[0].year, to: trend[trend.length - 1].year } : null
  const est = f.estimates

  const groups: { title: string; rows: { k: string; v: string }[] }[] = [
    {
      title: tl.valuationGroup,
      rows: [
        { k: tl.trailingPe, v: fixed(f.valuation.trailing_pe, 1) },
        { k: tl.forwardPe, v: fixed(f.valuation.forward_pe, 1) },
        { k: tl.peg, v: fixed(f.valuation.peg, 2) },
        { k: tl.priceToBook, v: fixed(f.valuation.price_to_book, 1) },
        { k: tl.evEbitda, v: fixed(f.valuation.ev_to_ebitda, 1) },
        { k: tl.fcfYield, v: pct(f.valuation.fcf_yield, 1) },
      ],
    },
    {
      title: tl.qualityGroup,
      rows: [
        { k: tl.roe, v: pct(f.quality.roe, 0) },
        { k: tl.profitMargin, v: pct(f.quality.profit_margin, 0) },
        { k: tl.operatingMargin, v: pct(f.quality.operating_margin, 0) },
        { k: tl.debtToEquity, v: f.quality.debt_to_equity != null ? `${(f.quality.debt_to_equity / 100).toFixed(2)}x` : DASH },
        { k: tl.currentRatio, v: fixed(f.quality.current_ratio, 2) },
      ],
    },
    {
      title: tl.growthGroup,
      rows: [
        { k: tl.revenueGrowth, v: spct(f.growth.revenue_growth, 1) },
        { k: tl.earningsGrowth, v: spct(f.growth.earnings_growth, 1) },
        ...(span ? [
          { k: fill(tl.revenueCagr, span), v: spct(f.growth.revenue_cagr, 1) },
          { k: fill(tl.netIncomeCagr, span), v: spct(f.growth.net_income_cagr, 1) },
        ] : []),
      ],
    },
    {
      title: tl.dividendGroup,
      rows: [
        { k: tl.dividendYield, v: pct(f.dividend.yield, 2) },
        { k: tl.payoutRatio, v: pct(f.dividend.payout_ratio, 0) },
        { k: tl.fiveYearYield, v: pct(f.dividend.five_year_avg_yield, 2) },
      ],
    },
    {
      title: tl.estimatesGroup,
      rows: [
        { k: tl.revisionMomentum, v: spct(est.revision_momentum, 1) },
        ...(est.up_30d != null || est.down_30d != null
          ? [{ k: '', v: fill(tl.revisionsCount, { up: est.up_30d ?? 0, down: est.down_30d ?? 0 }) }] : []),
      ],
    },
  ]

  return (
    <Panel
      title={tl.fundamentalsTitle}
      subtitle={[f.sector, f.industry, f.market_cap != null ? `${tl.marketCap} ${compactMoney(f.market_cap, currency)}` : null].filter(Boolean).join(' · ') || undefined}
    >
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
        {groups.map((g) => (
          <div key={g.title} className="flex flex-col gap-1.5 min-w-0">
            <h3 className="text-[13px] font-semibold" style={{ color: theme.colors.text }}>{g.title}</h3>
            <dl className="flex flex-col">
              {g.rows.map((row, i) => (
                <div key={`${row.k}-${i}`} className="flex items-baseline justify-between gap-3 py-1.5 min-w-0" style={{ borderBottom: `1px solid ${theme.colors.border}` }}>
                  <dt className="text-[12.5px] min-w-0" style={{ color: theme.colors.textSub }}>{row.k}</dt>
                  <dd className="text-[13px] tabular-nums text-right shrink-0" style={{ ...mono, color: theme.colors.text }}>{row.v}</dd>
                </div>
              ))}
            </dl>
          </div>
        ))}
      </div>
    </Panel>
  )
}
