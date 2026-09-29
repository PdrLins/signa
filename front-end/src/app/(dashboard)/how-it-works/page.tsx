'use client'

import Link from 'next/link'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { Panel } from '@/components/insights/Panel'

const PAGE_LINKS = ['/today', '/signals', '/positions', '/performance', '/brain', '/settings']

export default function HowItWorksPage() {
  const theme = useTheme()
  const h = useI18nStore((s) => s.t).howItWorks
  const text = { color: theme.colors.text }
  const sub = { color: theme.colors.textSub }

  return (
    <div className="flex flex-col gap-4 md:gap-6 max-w-[960px]">
      <header className="flex flex-col gap-2">
        <h1 className="text-[26px] md:text-[30px] font-semibold tracking-tight" style={text}>{h.title}</h1>
        <p className="text-sm leading-relaxed" style={sub}>{h.subtitle}</p>
      </header>

      <div
        className="rounded-2xl px-5 py-4 flex flex-col gap-1"
        style={{ backgroundColor: theme.colors.surface, border: `1px solid ${theme.colors.warning}4D` }}
      >
        <p className="text-sm font-semibold" style={text}>{h.paperTitle}</p>
        <p className="text-sm" style={sub}>{h.paperDesc}</p>
      </div>

      <Panel title={h.funnelTitle} subtitle={h.funnelDesc}>
        <ol className="flex flex-col">
          {h.steps.map((s, i) => {
            const last = i === h.steps.length - 1
            return (
              <li key={s.title} className="grid grid-cols-[32px_minmax(0,1fr)] gap-3 md:gap-4">
                <div className="flex flex-col items-center" aria-hidden="true">
                  <span
                    className="w-7 h-7 rounded-full grid place-items-center text-[13px] font-semibold"
                    style={{ backgroundColor: theme.colors.surfaceAlt, border: `2px solid ${theme.colors.primary}`, color: theme.colors.text }}
                  >
                    {i + 1}
                  </span>
                  {!last && <span className="flex-1 w-0.5 mt-1" style={{ backgroundColor: theme.colors.surfaceAlt }} />}
                </div>
                <div className={`flex flex-col gap-1 ${last ? '' : 'pb-5'}`}>
                  <h3 className="text-[15px] font-semibold" style={text}>{s.title}</h3>
                  <p className="text-[13px] leading-relaxed" style={sub}>{s.desc}</p>
                </div>
              </li>
            )
          })}
        </ol>
      </Panel>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 md:gap-5">
        <Panel title={h.breakerTitle}><p className="text-[13px] leading-relaxed" style={sub}>{h.breakerDesc}</p></Panel>
        <Panel title={h.scoreTitle}><p className="text-[13px] leading-relaxed" style={sub}>{h.scoreDesc}</p></Panel>
        <Panel title={h.learningTitle}><p className="text-[13px] leading-relaxed" style={sub}>{h.learningDesc}</p></Panel>
        <Panel title={h.scansTitle}><p className="text-[13px] leading-relaxed" style={sub}>{h.scansDesc}</p></Panel>
      </div>

      <Panel title={h.pagesTitle}>
        <ul className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {h.pages.map((pg, i) => (
            <li key={pg.title}>
              <Link
                href={PAGE_LINKS[i] ?? '/today'}
                className="block rounded-xl p-3.5 h-full transition-opacity hover:opacity-90 focus-visible:outline focus-visible:outline-2"
                style={{ backgroundColor: theme.colors.surfaceAlt, outlineColor: theme.colors.primary }}
              >
                <span className="block text-sm font-semibold" style={text}>{pg.title}</span>
                <span className="block text-[13px] mt-1 leading-relaxed" style={sub}>{pg.desc}</span>
              </Link>
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  )
}
