'use client'

import { Fragment, memo } from 'react'
import Link from 'next/link'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { fill } from '@/lib/insights'

/** A ticker that opens its stock page (/stocks/{symbol}). */
export const SymbolLink = memo(function SymbolLink({ symbol, className = 'font-semibold', label }: {
  symbol: string
  className?: string
  /** visible text (defaults to the symbol) */
  label?: string
}) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  return (
    <Link href={`/stocks/${encodeURIComponent(symbol)}`} aria-label={fill(t.stock.openPage, { symbol })}
      className={`${className} underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 rounded-sm`}
      style={{ color: 'inherit', outlineColor: theme.colors.primary }}>
      {label ?? symbol}
    </Link>
  )
})

/** A translated sentence with a `{symbols}` slot rendered as links:
 *  "No dividend: ENB.TO, T." with each ticker opening its stock page. */
export function SymbolListText({ template, symbols }: { template: string; symbols: string[] }) {
  const [before, after = ''] = template.split('{symbols}')
  return (
    <>
      {before}
      {symbols.map((s, i) => (
        <Fragment key={s}>
          {i > 0 && ', '}
          <SymbolLink symbol={s} className="font-medium underline" />
        </Fragment>
      ))}
      {after}
    </>
  )
}
