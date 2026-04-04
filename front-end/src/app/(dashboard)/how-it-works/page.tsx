'use client'

import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { Card } from '@/components/ui/Card'

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  const theme = useTheme()
  return (
    <div className="space-y-2">
      <h2 className="text-lg font-bold" style={{ color: theme.colors.text }}>{title}</h2>
      {children}
    </div>
  )
}

function P({ children }: { children: React.ReactNode }) {
  const theme = useTheme()
  return <p className="text-sm leading-relaxed" style={{ color: theme.colors.textSub }}>{children}</p>
}

function Li({ children }: { children: React.ReactNode }) {
  const theme = useTheme()
  return (
    <li className="text-sm leading-relaxed flex gap-2" style={{ color: theme.colors.textSub }}>
      <span style={{ color: theme.colors.primary }}>*</span>
      <span>{children}</span>
    </li>
  )
}

function Step({ title, desc }: { title: string; desc: string }) {
  const theme = useTheme()
  return (
    <div
      className="rounded-xl px-4 py-3"
      style={{ backgroundColor: theme.colors.surfaceAlt, border: `0.5px solid ${theme.colors.border}` }}
    >
      <p className="text-sm font-bold mb-1" style={{ color: theme.colors.text }}>{title}</p>
      <p className="text-xs leading-relaxed" style={{ color: theme.colors.textSub }}>{desc}</p>
    </div>
  )
}

export default function HowItWorksPage() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const h = t.howItWorks

  return (
    <div className="space-y-6 max-w-[720px]">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold" style={{ color: theme.colors.text }}>{h.title}</h1>
        <p className="text-sm mt-1" style={{ color: theme.colors.textSub }}>{h.subtitle}</p>
      </div>

      {/* Goal */}
      <Card>
        <Section title={h.goalTitle}>
          <P>{h.goalDesc}</P>
        </Section>
      </Card>

      {/* Who */}
      <Card>
        <Section title={h.whoTitle}>
          <P>{h.whoDesc}</P>
        </Section>
      </Card>

      {/* Scans */}
      <Card>
        <Section title={h.scanTitle}>
          <P>{h.scanDesc}</P>
          <div className="space-y-2 mt-2">
            <Step title="06:00 AM ET" desc={h.scan1} />
            <Step title="10:00 AM ET" desc={h.scan2} />
            <Step title="03:00 PM ET" desc={h.scan3} />
            <Step title="04:30 PM ET" desc={h.scan4} />
          </div>
          <P>{h.scanNote}</P>
          <h3 className="text-sm font-bold mt-4" style={{ color: theme.colors.text }}>{h.scanOnDemand}</h3>
          <P>{h.scanOnDemandDesc}</P>
        </Section>
      </Card>

      {/* Pipeline */}
      <Card>
        <Section title={h.pipelineTitle}>
          <P>{h.pipelineDesc}</P>
          <div className="space-y-2 mt-2">
            <Step title={h.step1Title} desc={h.step1Desc} />
            <Step title={h.step2Title} desc={h.step2Desc} />
            <Step title={h.step3Title} desc={h.step3Desc} />
            <Step title={h.step4Title} desc={h.step4Desc} />
            <Step title={h.step5Title} desc={h.step5Desc} />
            <Step title={h.step6Title} desc={h.step6Desc} />
            <Step title={h.step7Title} desc={h.step7Desc} />
          </div>
        </Section>
      </Card>

      {/* Signals */}
      <Card>
        <Section title={h.signalsTitle}>
          <h3 className="text-sm font-bold mt-2" style={{ color: theme.colors.text }}>{h.actionsTitle}</h3>
          <ul className="space-y-1.5 mt-1">
            <Li>{h.buyDesc}</Li>
            <Li>{h.holdDesc}</Li>
            <Li>{h.avoidDesc}</Li>
            <Li>{h.sellDesc}</Li>
          </ul>

          <h3 className="text-sm font-bold mt-4" style={{ color: theme.colors.text }}>{h.statusTitle}</h3>
          <ul className="space-y-1.5 mt-1">
            <Li>{h.confirmedDesc}</Li>
            <Li>{h.weakDesc}</Li>
            <Li>{h.upgradedDesc}</Li>
            <Li>{h.cancelledDesc}</Li>
          </ul>
        </Section>
      </Card>

      {/* GEMs */}
      <Card>
        <Section title={h.gemsTitle}>
          <P>{h.gemsDesc}</P>
          <ul className="space-y-1.5 mt-2">
            <Li>{h.gem1}</Li>
            <Li>{h.gem2}</Li>
            <Li>{h.gem3}</Li>
            <Li>{h.gem4}</Li>
            <Li>{h.gem5}</Li>
          </ul>
          <div className="mt-3">
            <P>{h.gemsNote}</P>
          </div>
        </Section>
      </Card>

      {/* Buckets */}
      <Card>
        <Section title={h.bucketsTitle}>
          <div className="space-y-3 mt-1">
            <div
              className="rounded-xl px-4 py-3"
              style={{ backgroundColor: theme.colors.up + '10', border: `0.5px solid ${theme.colors.up}30` }}
            >
              <p className="text-sm font-bold mb-1" style={{ color: theme.colors.up }}>{h.safeTitle}</p>
              <p className="text-xs leading-relaxed" style={{ color: theme.colors.textSub }}>{h.safeDesc}</p>
            </div>
            <div
              className="rounded-xl px-4 py-3"
              style={{ backgroundColor: theme.colors.primary + '10', border: `0.5px solid ${theme.colors.primary}30` }}
            >
              <p className="text-sm font-bold mb-1" style={{ color: theme.colors.primary }}>{h.riskTitle}</p>
              <p className="text-xs leading-relaxed" style={{ color: theme.colors.textSub }}>{h.riskDesc}</p>
            </div>
          </div>
        </Section>
      </Card>

      {/* Watchlist */}
      <Card>
        <Section title={h.watchlistTitle}>
          <P>{h.watchlistDesc}</P>
        </Section>
      </Card>

      {/* Telegram */}
      <Card>
        <Section title={h.telegramTitle}>
          <P>{h.telegramDesc}</P>
          <ul className="space-y-1.5 mt-2">
            <Li>{h.tg1}</Li>
            <Li>{h.tg2}</Li>
            <Li>{h.tg3}</Li>
            <Li>{h.tg4}</Li>
          </ul>
          <div className="mt-3">
            <P>{h.telegramNote}</P>
          </div>
        </Section>
      </Card>

      {/* Risk Levels */}
      <Card>
        <Section title={h.riskTitle}>
          <P>{h.riskDesc}</P>
          <ul className="space-y-1.5 mt-2">
            <Li>{h.riskLow}</Li>
            <Li>{h.riskMed}</Li>
            <Li>{h.riskHigh}</Li>
          </ul>
        </Section>
      </Card>

      {/* How Scoring Works */}
      <Card>
        <Section title={h.scoringTitle}>
          <P>{h.scoringDesc}</P>
          <ul className="space-y-1.5 mt-2">
            <Li>{h.scoringSafe}</Li>
            <Li>{h.scoringRisk}</Li>
          </ul>
          <div className="mt-3">
            <P>{h.scoringNote}</P>
          </div>
        </Section>
      </Card>

      {/* Signal Blockers */}
      <Card>
        <Section title={h.blockersTitle}>
          <P>{h.blockersDesc}</P>
          <ul className="space-y-1.5 mt-2">
            <Li>{h.blocker1}</Li>
            <Li>{h.blocker2}</Li>
            <Li>{h.blocker3}</Li>
            <Li>{h.blocker4}</Li>
          </ul>
        </Section>
      </Card>

      {/* Ticker Detail Page */}
      <Card>
        <Section title={h.detailTitle}>
          <P>{h.detailDesc}</P>
        </Section>
      </Card>

      {/* Themes */}
      <Card>
        <Section title={h.themesTitle}>
          <P>{h.themesDesc}</P>
        </Section>
      </Card>

      {/* Tips */}
      <Card>
        <Section title={h.tipsTitle}>
          <ul className="space-y-1.5">
            <Li>{h.tip1}</Li>
            <Li>{h.tip2}</Li>
            <Li>{h.tip3}</Li>
            <Li>{h.tip4}</Li>
            <Li>{h.tip5}</Li>
            <Li>{h.tip6}</Li>
          </ul>
        </Section>
      </Card>
    </div>
  )
}
