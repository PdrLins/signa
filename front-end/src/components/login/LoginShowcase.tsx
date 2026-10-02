'use client'

import Link from 'next/link'
import { CalendarDays, Wallet, Bell, ShieldCheck } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { AppVersion } from '@/components/ui/AppVersion'

/** Left side of the login page on desktop: what Signa is, with a small
 *  illustrative preview of the app (sample figures, labelled as such). */
export function LoginShowcase() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const tl = t.login
  const c = theme.colors

  const points = [
    { icon: Wallet, label: tl.featureScanning, desc: tl.featureScanningDesc },
    { icon: CalendarDays, label: tl.featureAi, desc: tl.featureAiDesc },
    { icon: Bell, label: tl.featureAlerts, desc: tl.featureAlertsDesc },
  ]

  return (
    <aside
      className="hidden lg:flex flex-col justify-between w-[540px] shrink-0 p-12 gap-10 relative overflow-hidden"
      style={{ backgroundColor: c.nav, borderRight: `1px solid ${c.border}` }}
    >
      <div
        aria-hidden="true"
        className="absolute -top-40 -right-40 w-[420px] h-[420px] rounded-full opacity-[0.08] blur-3xl"
        style={{ backgroundColor: c.primary }}
      />

      <div className="relative flex flex-col gap-4">
        <p className="text-[15px] font-bold tracking-tight" style={{ color: c.text }}>Signa</p>
        <h1 className="text-[34px] leading-[1.1] font-bold tracking-tight max-w-[420px]" style={{ color: c.text }}>
          {tl.subtitle}
        </h1>
        <p className="text-[15px] leading-relaxed max-w-[420px]" style={{ color: c.textSub }}>{tl.tagline}</p>
      </div>

      {/* Illustrative preview — sample numbers, not the user's */}
      <div className="relative flex flex-col gap-3 max-w-[420px]" aria-label={tl.previewLabel} role="img">
        <div className="rounded-2xl p-4 flex flex-col gap-2" style={{ backgroundColor: c.surface, border: `1px solid ${c.border}` }}>
          <div className="flex items-baseline justify-between">
            <span className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: c.textSub }}>{tl.previewPortfolio}</span>
            <span className="text-[11px]" style={{ color: c.textHint }}>{tl.previewExample}</span>
          </div>
          <div className="flex items-baseline gap-3">
            <span className="text-[26px] font-bold tabular-nums" style={{ color: c.text }}>C$128,460</span>
            <span className="text-[13px] font-semibold tabular-nums" style={{ color: c.up }}>+C$452 (+0.35%)</span>
          </div>
          <svg viewBox="0 0 380 64" className="w-full h-16" aria-hidden="true">
            <line x1="0" y1="40" x2="380" y2="40" stroke={c.border} strokeDasharray="3 4" />
            <path d="M0 44 L30 41 L60 46 L90 38 L120 40 L150 33 L180 36 L210 28 L240 30 L270 22 L300 25 L330 16 L360 18 L380 12"
              fill="none" stroke={c.up} strokeWidth="2.2" strokeLinejoin="round" />
          </svg>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-2xl p-4 flex flex-col gap-1" style={{ backgroundColor: c.surface, border: `1px solid ${c.border}` }}>
            <span className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: c.textSub }}>{tl.previewDividends}</span>
            <span className="text-[18px] font-bold tabular-nums" style={{ color: c.text }}>C$1,044<span className="text-[12px] font-medium" style={{ color: c.textSub }}> {tl.previewPerMonth}</span></span>
            <span className="text-[12px]" style={{ color: c.textSub }}>{tl.previewNext12m}</span>
          </div>
          <div className="rounded-2xl p-4 flex flex-col gap-1" style={{ backgroundColor: c.surface, border: `1px solid ${c.border}` }}>
            <span className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: c.textSub }}>{tl.previewComingUp}</span>
            <span className="text-[14px] font-semibold" style={{ color: c.text }}>{tl.previewEvent}</span>
            <span className="text-[12px] font-semibold tabular-nums" style={{ color: c.up }}>+C$48.50</span>
          </div>
        </div>
      </div>

      <div className="relative flex flex-col gap-5">
        <ul className="flex flex-col gap-4">
          {points.map((p) => (
            <li key={p.label} className="flex items-start gap-3">
              <span className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0" style={{ backgroundColor: c.surfaceAlt }}>
                <p.icon size={17} aria-hidden="true" style={{ color: c.primary }} />
              </span>
              <span className="flex flex-col">
                <span className="text-[14px] font-semibold" style={{ color: c.text }}>{p.label}</span>
                <span className="text-[13px]" style={{ color: c.textSub }}>{p.desc}</span>
              </span>
            </li>
          ))}
        </ul>
        <div className="flex items-center gap-4 text-[13px]" style={{ color: c.textSub }}>
          <Link href="/pricing" className="font-medium hover:underline" style={{ color: c.primary }}>{t.pricing.seePlans}</Link>
          <span className="flex items-center gap-1.5"><ShieldCheck size={14} aria-hidden="true" />{tl.notAdvice}</span>
        </div>
        <AppVersion />
      </div>
    </aside>
  )
}
