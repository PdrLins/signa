'use client'

import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { StatTile } from '@/components/insights/Panel'
import { fill, money, signedPct, DASH } from '@/lib/insights'
import type { TodayStatus } from '@/types/insights'

interface IntegrationsCache {
  integrations: Record<string, { ok: boolean }>
}

export function StatusStrip({ status }: { status: TodayStatus }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const s = t.today.status

  // Integrations are NOT probed from here (the probe calls every provider).
  // Show the last result the Integrations page cached, else link to it.
  const { data: integ } = useQuery<IntegrationsCache>({ queryKey: ['health', 'integrations'], enabled: false })
  const down = integ ? Object.values(integ.integrations ?? {}).filter((i) => !i.ok).length : null

  const paused = status.breaker.state === 'paused'
  const breakerColor = paused ? theme.colors.warning : theme.colors.up
  const change = status.change_pct
  const invested = status.invested_pct != null ? `${Math.round(status.invested_pct)}%` : DASH
  const spend = status.ai_spend
  const spendPct = spend && spend.budget_usd > 0 ? Math.min(100, (spend.month_usd / spend.budget_usd) * 100) : null

  return (
    <section aria-label={s.label} className="grid grid-cols-2 lg:grid-cols-5 gap-2.5 md:gap-3.5">
      <StatTile
        label={s.equity}
        value={status.equity != null ? money(status.equity) : DASH}
        sub={
          <>
            <span className="tabular-nums" style={{ color: change == null ? theme.colors.textSub : change >= 0 ? theme.colors.up : theme.colors.down, fontFamily: 'var(--font-mono)' }}>
              {signedPct(change)}
            </span>{' '}
            {s.vsSpy}{' '}
            <span className="tabular-nums" style={{ fontFamily: 'var(--font-mono)' }}>{signedPct(status.spy_change_pct)}</span>
            <span className="hidden md:inline"> {s.sinceReset}</span>
          </>
        }
      />
      <StatTile
        label={<><span className="hidden md:inline">{s.openPositions}</span><span className="md:hidden">{s.positionsShort}</span></>}
        value={
          <>
            {status.open_positions}{' '}
            <span className="text-[13px] md:text-[15px]" style={{ color: theme.colors.textSub }}>/ {status.max_positions}</span>
          </>
        }
        sub={
          <>
            <span className="hidden md:inline">{fill(s.investedLine, { amount: money(status.invested_usd, 0), pct: invested })}</span>
            <span className="md:hidden">{fill(s.investedShort, { pct: invested })}</span>
          </>
        }
      />
      <div
        className="rounded-[14px] p-3.5 md:p-[18px] flex flex-col gap-1.5 md:gap-2 min-w-0"
        style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.border}` }}
      >
        <span className="text-[12px]" style={{ color: theme.colors.textSub }}>
          <span className="hidden md:inline">{s.breaker}</span><span className="md:hidden">{s.breakerShort}</span>
        </span>
        <span className="text-[16px] md:text-[20px] font-semibold flex items-center gap-2" style={{ color: breakerColor }}>
          <span aria-hidden="true" className="w-[9px] h-[9px] rounded-full" style={{ backgroundColor: breakerColor }} />
          {paused ? s.paused : s.normal}
        </span>
        <span className="text-[12px] leading-snug" style={{ color: theme.colors.textSub }}>
          {paused && status.breaker.days_remaining != null
            ? fill(s.daysLeft, { days: status.breaker.days_remaining })
            : <>
                <span className="tabular-nums" style={{ fontFamily: 'var(--font-mono)' }}>
                  {fill(s.fromPeak, { pct: signedPct(status.drawdown_pct, 1) })}
                </span>
                <span className="hidden md:inline"> · {fill(s.pausesAt, { pct: `−${status.breaker.limit_pct}%` })}</span>
              </>}
        </span>
      </div>
      <div
        className="rounded-[14px] p-3.5 md:p-[18px] flex flex-col gap-1.5 md:gap-2 min-w-0"
        style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.border}` }}
      >
        <span className="text-[12px]" style={{ color: theme.colors.textSub }}>
          <span className="hidden md:inline">{s.aiSpend}</span><span className="md:hidden">{s.aiSpendShort}</span>
        </span>
        <span className="text-[19px] md:text-[24px] font-medium tabular-nums" style={{ color: theme.colors.text, fontFamily: 'var(--font-mono)' }}>
          {spend ? money(spend.month_usd) : DASH}{' '}
          {spend && spend.budget_usd > 0 && (
            <span className="hidden md:inline text-[15px]" style={{ color: theme.colors.textSub }}>/ {money(spend.budget_usd, 0)}</span>
          )}
        </span>
        {spend && spendPct != null ? (
          <>
            <div
              className="hidden md:block h-1.5 rounded-full overflow-hidden"
              style={{ backgroundColor: theme.colors.surfaceAlt }}
              role="progressbar"
              aria-valuenow={Math.round(spendPct)}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label={s.aiSpend}
            >
              <div className="h-full rounded-full" style={{ width: `${spendPct}%`, backgroundColor: spendPct >= 90 ? theme.colors.warning : theme.colors.primary }} />
            </div>
            <span className="md:hidden text-[12px]" style={{ color: theme.colors.textSub }}>
              {fill(s.ofBudget, { budget: money(spend.budget_usd, 0) })}
            </span>
          </>
        ) : (
          <span className="text-[12px]" style={{ color: theme.colors.textSub }}>{s.noBudget}</span>
        )}
        {spend?.breakdown && spend.breakdown.length > 0 && (
          <div className="flex flex-col gap-0.5 text-[11px] md:text-[12px] tabular-nums" style={{ color: theme.colors.textSub }}>
            <span>
              {spend.breakdown.filter((b) => !b.local).map((b, i) => (
                <span key={b.provider}>
                  {i > 0 && ' · '}
                  {s.providers[b.provider as keyof typeof s.providers] ?? b.provider}{' '}
                  <span style={{ color: theme.colors.text, fontFamily: 'var(--font-mono)' }}>{money(b.cost_usd)}</span>
                </span>
              ))}
            </span>
            <span>
              {s.localFree}{' '}
              {spend.breakdown.filter((b) => b.local).map((b, i) => (
                <span key={b.provider}>
                  {i > 0 && ' · '}
                  {s.providers[b.provider as keyof typeof s.providers] ?? b.provider} {fill(s.callsN, { n: b.calls })}
                </span>
              ))}
            </span>
          </div>
        )}
      </div>
      <div
        className="hidden lg:flex rounded-[14px] p-[18px] flex-col gap-2 min-w-0"
        style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.border}` }}
      >
        <span className="text-[12px]" style={{ color: theme.colors.textSub }}>{s.integrations}</span>
        {down == null ? (
          <Link
            href="/integrations"
            className="text-[13px] leading-snug underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 rounded"
            style={{ color: theme.colors.accent, outlineColor: theme.colors.primary }}
          >
            {s.checkStatus} →
          </Link>
        ) : (
          <>
            <span className="text-[20px] font-semibold" style={{ color: down === 0 ? theme.colors.text : theme.colors.warning }}>
              {down === 0 ? s.allConnected : fill(s.needAttention, { n: down })}
            </span>
            <Link href="/integrations" className="text-[12px] hover:underline" style={{ color: theme.colors.textSub }}>
              {Object.keys(integ?.integrations ?? {}).join(' · ')}
            </Link>
          </>
        )}
      </div>
    </section>
  )
}
