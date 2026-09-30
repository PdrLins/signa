'use client'

import { useCallback, useMemo } from 'react'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Briefcase, ExternalLink, SearchX, Star } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useToast } from '@/hooks/useToast'
import { useAccess } from '@/hooks/useAccess'
import { useStock, stockKey } from '@/hooks/useStock'
import { useAddTicker, useRemoveTicker } from '@/hooks/useWatchlist'
import { CheckApiError } from '@/lib/api'
import { ApiAccessError } from '@/lib/access'
import { checkHref } from '@/lib/check'
import { DASH, etTime, fill, nativePrice, shortDate, signedPct } from '@/lib/insights'
import { Panel } from '@/components/insights/Panel'
import { Skeleton } from '@/components/ui/Skeleton'
import { PriceChart } from '@/components/charts/PriceChart'
import { DividendPanel } from '@/components/check/DividendPanel'
import { StockChecks, compactMoney } from '@/components/stock/StockChecks'
import { StockEvents } from '@/components/stock/StockEvents'
import type { StockPage } from '@/types/stock'

const BTN = 'min-h-[44px] px-4 rounded-xl text-[14px] font-medium flex items-center justify-center gap-2 focus-visible:outline focus-visible:outline-2 disabled:opacity-60'

function LoadingState({ label }: { label: string }) {
  return (
    <div className="space-y-4" role="status" aria-busy="true" aria-label={label}>
      <Skeleton width={220} height={30} />
      <Skeleton width={160} height={18} />
      <Skeleton width="100%" height={240} borderRadius={16} />
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Skeleton width="100%" height={300} borderRadius={16} />
        <Skeleton width="100%" height={300} borderRadius={16} />
      </div>
    </div>
  )
}

function RangeBar({ low, high, price, currency, symbol }: {
  low: number; high: number; price: number; currency: string; symbol: string
}) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const pos = high > low ? Math.min(100, Math.max(0, ((price - low) / (high - low)) * 100)) : 50
  return (
    <div className="min-w-0">
      <p className="text-[11.5px] mb-1.5" style={{ color: theme.colors.textSub }}>{t.stock.range52w}</p>
      <div className="h-1.5 rounded-full relative" style={{ backgroundColor: theme.colors.surfaceAlt }}
        role="img" aria-label={`${t.stock.range52w}: ${nativePrice(low, symbol, currency)} – ${nativePrice(high, symbol, currency)}`}>
        <div className="absolute w-3 h-3 rounded-full -top-[3px]"
          style={{ backgroundColor: theme.colors.primary, border: `2px solid ${theme.colors.surface}`, left: `${pos}%`, transform: 'translateX(-50%)' }} />
      </div>
      <div className="flex justify-between mt-1.5 text-[11.5px] tabular-nums" style={{ color: theme.colors.textHint }}>
        <span>{t.stock.low} {nativePrice(low, symbol, currency)}</span>
        <span>{t.stock.high} {nativePrice(high, symbol, currency)}</span>
      </div>
    </div>
  )
}

function Header({ data }: { data: StockPage }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const ts = t.stock
  const q = data.quote
  const chg = q.change_pct
  const chgColor = chg == null || chg === 0 ? theme.colors.textSub : chg > 0 ? theme.colors.up : theme.colors.down
  const meta = useMemo(
    () => [data.exchange_name || data.exchange, ts.assetTypes[data.asset_type] ?? data.asset_type, data.sector]
      .filter(Boolean).join(' · '),
    [data, ts],
  )
  const asOf = q.as_of ? `${shortDate(q.as_of, locale)} ${etTime(q.as_of, locale)}` : null

  return (
    <Panel>
      <div className="flex flex-col gap-4 min-w-0">
        <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2 min-w-0">
          <div className="min-w-0">
            <h1 className="text-2xl font-bold flex flex-wrap items-baseline gap-x-2" style={{ color: theme.colors.text }}>
              <span className="font-mono">{data.symbol}</span>
              {data.name && <span className="text-[15px] font-medium break-words" style={{ color: theme.colors.textSub }}>{data.name}</span>}
            </h1>
            <p className="text-[12.5px] mt-0.5" style={{ color: theme.colors.textHint }}>{meta}</p>
            {data.followed.in_holdings && (
              <p className="text-[12px] mt-1.5 inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full"
                style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.primary }}>
                <Briefcase size={12} aria-hidden="true" />{ts.inHoldings}
              </p>
            )}
          </div>
          <div className="text-left sm:text-right shrink-0">
            <p className="text-[26px] font-bold tabular-nums leading-tight" style={{ color: theme.colors.text }}>
              {nativePrice(q.price, data.symbol, data.currency)}
            </p>
            <p className="text-[13px] font-semibold tabular-nums" style={{ color: chgColor }}>
              {chg == null ? DASH : `${signedPct(chg, 2)} ${ts.today}`}
            </p>
            {asOf && <p className="text-[11px]" style={{ color: theme.colors.textHint }}>{fill(ts.asOf, { time: asOf })}</p>}
          </div>
        </div>
        {(q.low_52w != null && q.high_52w != null && q.price != null) || q.market_cap != null ? (
          <div className="grid grid-cols-1 sm:grid-cols-[minmax(0,1fr)_auto] gap-4 items-end">
            {q.low_52w != null && q.high_52w != null && q.price != null ? (
              <RangeBar low={q.low_52w} high={q.high_52w} price={q.price} currency={data.currency} symbol={data.symbol} />
            ) : <span />}
            {q.market_cap != null && (
              <div className="sm:text-right">
                <p className="text-[11.5px]" style={{ color: theme.colors.textSub }}>{ts.marketCap}</p>
                <p className="text-[14px] font-semibold tabular-nums" style={{ color: theme.colors.text }}>
                  {compactMoney(q.market_cap, data.currency)}
                </p>
              </div>
            )}
          </div>
        ) : null}
      </div>
    </Panel>
  )
}

function Actions({ data }: { data: StockPage }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const ta = t.stock.actions
  const toast = useToast()
  const qc = useQueryClient()
  const { can } = useAccess()
  const add = useAddTicker()
  const remove = useRemoveTicker()
  const symbol = data.symbol
  const inWatchlist = data.followed.in_watchlist
  const busy = add.isPending || remove.isPending

  const onError = useCallback((err: unknown) => {
    if (err instanceof ApiAccessError && err.code === 'slot_limit') {
      toast.show(fill(t.access.slotLimit, { limit: err.limit ?? null }), 'error')
    } else if (err instanceof ApiAccessError && err.code === 'upgrade_required') {
      toast.show(t.access.upgradeRequired, 'error')
    } else {
      toast.show(ta.failed, 'error')
    }
  }, [t, ta, toast])

  const toggle = useCallback(() => {
    const done = (msg: string) => () => {
      toast.show(fill(msg, { symbol }), inWatchlist ? 'info' : 'success')
      qc.invalidateQueries({ queryKey: stockKey(symbol) })
    }
    if (inWatchlist) remove.mutate(symbol, { onSuccess: done(ta.removed), onError })
    else add.mutate(symbol, { onSuccess: done(ta.added), onError })
  }, [inWatchlist, symbol, add, remove, ta, toast, qc, onError])

  const canWatch = can('action.watchlist.edit')
  const canSignals = can('area.signals')
  const canCheck = can('area.check')
  if (!canWatch && !canSignals && !canCheck) return null

  const secondary = { backgroundColor: theme.colors.surfaceAlt, color: theme.colors.text, outlineColor: theme.colors.primary }
  return (
    <div className="flex flex-wrap gap-2">
      {canWatch && (
        <button type="button" onClick={toggle} disabled={busy} aria-pressed={inWatchlist}
          aria-label={`${inWatchlist ? ta.removeWatchlist : ta.addWatchlist} ${symbol}`}
          className={BTN}
          style={inWatchlist ? secondary : { backgroundColor: theme.colors.primary, color: theme.colors.surface, outlineColor: theme.colors.primary }}>
          <Star size={16} aria-hidden="true" fill={inWatchlist ? theme.colors.warning : 'none'}
            style={{ color: inWatchlist ? theme.colors.warning : theme.colors.surface }} />
          {inWatchlist ? ta.inWatchlist : ta.addWatchlist}
        </button>
      )}
      {canSignals && (
        <Link href={`/signals/${encodeURIComponent(symbol)}`} className={BTN} style={secondary}
          aria-label={`${ta.openSignals} ${symbol}`}>
          {ta.openSignals}
        </Link>
      )}
      {canCheck && (
        <Link href={checkHref(symbol, 'long')} className={BTN} style={secondary} aria-label={`${ta.checkAi} ${symbol}`}>
          {ta.checkAi}<ExternalLink size={14} aria-hidden="true" />
        </Link>
      )}
    </div>
  )
}

export default function StockPageView() {
  const params = useParams()
  const router = useRouter()
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const ts = t.stock
  const raw = decodeURIComponent(String(params.symbol ?? '')).toUpperCase()
  const { data, isLoading, error, refetch, isFetching } = useStock(raw)

  const notFound = error instanceof CheckApiError && (error.status === 404 || error.status === 400)

  const back = (
    <button type="button" onClick={() => router.back()}
      className="self-start inline-flex items-center gap-1 min-h-[44px] pr-2 rounded-lg text-[13px] focus-visible:outline focus-visible:outline-2"
      style={{ color: theme.colors.accent, outlineColor: theme.colors.primary }} aria-label={ts.back}>
      <ArrowLeft size={16} aria-hidden="true" />{ts.back}
    </button>
  )

  if (isLoading) {
    return <div className="space-y-2 pb-4 min-w-0">{back}<LoadingState label={fill(ts.loadingLabel, { symbol: raw })} /></div>
  }

  if (error || !data) {
    return (
      <div className="space-y-2 pb-4 min-w-0">
        {back}
        <Panel>
          <div className="flex flex-col items-start gap-3" role="alert">
            <SearchX size={28} aria-hidden="true" style={{ color: notFound ? theme.colors.textSub : theme.colors.down }} />
            <h1 className="text-[18px] font-semibold" style={{ color: theme.colors.text }}>
              {notFound ? fill(ts.notFoundTitle, { symbol: raw }) : ts.errorTitle}
            </h1>
            {notFound && <p className="text-[13px]" style={{ color: theme.colors.textSub }}>{ts.notFoundBody}</p>}
            {!notFound && (
              <button type="button" onClick={() => refetch()} disabled={isFetching} className={BTN}
                style={{ backgroundColor: theme.colors.surfaceAlt, color: theme.colors.text, outlineColor: theme.colors.primary }}
                aria-label={ts.retry}>
                {ts.retry}
              </button>
            )}
          </div>
        </Panel>
      </div>
    )
  }

  return (
    <div className="space-y-4 pb-4 min-w-0">
      {back}
      <Header data={data} />
      <Actions data={data} />
      <Panel>
        <PriceChart symbol={data.symbol} defaultRange="3M" title={ts.chartTitle} />
      </Panel>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start min-w-0">
        <StockChecks checks={data.checks} symbol={data.symbol} currency={data.currency} />
        <StockEvents events={data.events} symbol={data.symbol} currency={data.currency} />
      </div>
      <DividendPanel profile={data.dividend.profile} rules={data.dividend.rules} symbol={data.symbol} currency={data.currency} />
    </div>
  )
}
