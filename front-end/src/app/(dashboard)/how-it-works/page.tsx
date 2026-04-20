'use client'

import { useState } from 'react'
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

type TabKey = 'gettingStarted' | 'signals' | 'dailyUse' | 'brainAi' | 'accountsSetup' | 'reference'

const TAB_KEYS: TabKey[] = ['gettingStarted', 'signals', 'dailyUse', 'brainAi', 'accountsSetup', 'reference']

export default function HowItWorksPage() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const h = t.howItWorks
  const [activeTab, setActiveTab] = useState<TabKey>('gettingStarted')

  return (
    <div>
      {/* Header */}
      <div className="mb-6">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: theme.colors.text }}>{h.title}</h1>
          <p className="text-sm mt-1" style={{ color: theme.colors.textSub }}>{h.subtitle}</p>
        </div>
      </div>

      {/* Tab bar */}
      <div
        className="sticky top-0 z-10 -mx-1 px-1 pb-4 pt-1"
        style={{ backgroundColor: theme.colors.bg }}
      >
        <div
          className="inline-flex items-center gap-0.5 rounded-lg px-0.5 py-0.5 overflow-x-auto max-w-full"
          style={{ backgroundColor: theme.colors.nav }}
        >
          {TAB_KEYS.map((key) => {
            const isActive = activeTab === key
            return (
              <button
                key={key}
                onClick={() => setActiveTab(key)}
                className="px-2.5 py-1 rounded-md text-[11px] font-medium transition-all whitespace-nowrap"
                style={{
                  backgroundColor: isActive ? theme.colors.navActive : 'transparent',
                  color: isActive ? theme.colors.text : theme.colors.textSub,
                }}
              >
                {h.tabs[key]}
              </button>
            )
          })}
        </div>
      </div>

      {/* Tab content */}
      <div className="space-y-6">
        {activeTab === 'gettingStarted' && (
          <>
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
                  <Step title="12:00 PM ET" desc={h.scan2b} />
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
                  <Step title={h.discoveryTitle} desc={h.discoveryDesc} />
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
          </>
        )}

        {activeTab === 'signals' && (
          <>
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

            {/* Score Thresholds */}
            <Card>
              <Section title={h.scoreThresholdsTitle}>
                <P>{h.scoreThresholdsDesc}</P>
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

            {/* How to Read a Signal Card */}
            <Card>
              <Section title={h.readingCardTitle}>
                <P>{h.readingCardDesc}</P>
                <ul className="space-y-1.5 mt-2">
                  <Li>{h.readingCard1}</Li>
                  <Li>{h.readingCard2}</Li>
                  <Li>{h.readingCard3}</Li>
                  <Li>{h.readingCard4}</Li>
                  <Li>{h.readingCard5}</Li>
                  <Li>{h.readingCard6}</Li>
                  <Li>{h.readingCard7}</Li>
                  <Li>{h.readingCard8}</Li>
                </ul>
              </Section>
            </Card>

            {/* How to Read a Signal Detail Page */}
            <Card>
              <Section title={h.readingDetailTitle}>
                <P>{h.readingDetailDesc}</P>
                <ul className="space-y-1.5 mt-2">
                  <Li>{h.readingDetail1}</Li>
                  <Li>{h.readingDetail2}</Li>
                  <Li>{h.readingDetail3}</Li>
                  <Li>{h.readingDetail4}</Li>
                  <Li>{h.readingDetail5}</Li>
                  <Li>{h.readingDetail6}</Li>
                  <Li>{h.readingDetail7}</Li>
                  <Li>{h.readingDetail8}</Li>
                  <Li>{h.readingDetail9}</Li>
                  <Li>{h.readingDetail10}</Li>
                  <Li>{h.readingDetail11}</Li>
                </ul>
                <div
                  className="mt-3 rounded-xl px-4 py-3"
                  style={{ backgroundColor: theme.colors.surfaceAlt, border: `0.5px solid ${theme.colors.border}` }}
                >
                  <p className="text-xs leading-relaxed" style={{ color: theme.colors.textSub }}>{h.readingDetailExample}</p>
                </div>
              </Section>
            </Card>

            {/* Momentum vs Contrarian */}
            <Card>
              <Section title={h.dualSignalTitle}>
                <P>{h.dualSignalDesc}</P>
              </Section>
            </Card>

            {/* Price Display */}
            <Card>
              <Section title={h.priceDisplayTitle}>
                <P>{h.priceDisplayDesc}</P>
                <ul className="space-y-1.5 mt-2">
                  <Li>{h.priceDisplay1}</Li>
                  <Li>{h.priceDisplay2}</Li>
                </ul>
                <div className="mt-3">
                  <P>{h.priceDisplayNote}</P>
                </div>
              </Section>
            </Card>

            {/* Price Outlook */}
            <Card>
              <Section title={h.priceOutlookTitle}>
                <P>{h.priceOutlookDesc}</P>
              </Section>
            </Card>

            {/* Crypto vs Equity */}
            <Card>
              <Section title={h.cryptoTitle}>
                <P>{h.cryptoDesc}</P>
                <ul className="space-y-1.5 mt-2">
                  <Li>{h.crypto1}</Li>
                  <Li>{h.crypto2}</Li>
                  <Li>{h.crypto3}</Li>
                  <Li>{h.crypto4}</Li>
                </ul>
              </Section>
            </Card>
          </>
        )}

        {activeTab === 'dailyUse' && (
          <>
            {/* Daily Routine */}
            <Card>
              <Section title={h.dailyRoutineTitle}>
                <P>{h.dailyRoutineDesc}</P>
                <div className="space-y-2 mt-2">
                  <Step title={h.daily1Title} desc={h.daily1Desc} />
                  <Step title={h.daily2Title} desc={h.daily2Desc} />
                  <Step title={h.daily3Title} desc={h.daily3Desc} />
                  <Step title={h.daily4Title} desc={h.daily4Desc} />
                  <Step title={h.daily5Title} desc={h.daily5Desc} />
                  <Step title={h.daily6Title} desc={h.daily6Desc} />
                  <Step title={h.daily7Title} desc={h.daily7Desc} />
                </div>
              </Section>
            </Card>

            {/* What Should Make You Buy */}
            <Card>
              <Section title={h.whatShouldBuyTitle}>
                <P>{h.whatShouldBuyDesc}</P>
                <ul className="space-y-1.5 mt-2">
                  <Li>{h.shouldBuy1}</Li>
                  <Li>{h.shouldBuy2}</Li>
                  <Li>{h.shouldBuy3}</Li>
                  <Li>{h.shouldBuy4}</Li>
                  <Li>{h.shouldBuy5}</Li>
                  <Li>{h.shouldBuy6}</Li>
                </ul>
              </Section>
            </Card>

            {/* What Should Make You NOT Buy */}
            <Card>
              <Section title={h.whatShouldNotBuyTitle}>
                <P>{h.whatShouldNotBuyDesc}</P>
                <ul className="space-y-1.5 mt-2">
                  <Li>{h.shouldNotBuy1}</Li>
                  <Li>{h.shouldNotBuy2}</Li>
                  <Li>{h.shouldNotBuy3}</Li>
                  <Li>{h.shouldNotBuy4}</Li>
                  <Li>{h.shouldNotBuy5}</Li>
                  <Li>{h.shouldNotBuy6}</Li>
                </ul>
              </Section>
            </Card>

            {/* Understanding the Dashboard Cards */}
            <Card>
              <Section title={h.dashboardCardsTitle}>
                <P>{h.dashboardCardsDesc}</P>
                <ul className="space-y-1.5 mt-2">
                  <Li>{h.dashCard1}</Li>
                  <Li>{h.dashCard2}</Li>
                  <Li>{h.dashCard3}</Li>
                  <Li>{h.dashCard4}</Li>
                  <Li>{h.dashCard5}</Li>
                  <Li>{h.dashCard6}</Li>
                </ul>
              </Section>
            </Card>

            {/* Quick Actions */}
            <Card>
              <Section title={h.quickActionsTitle}>
                <P>{h.quickActionsDesc}</P>
              </Section>
            </Card>

            {/* Watchlist */}
            <Card>
              <Section title={h.watchlistTitle}>
                <P>{h.watchlistDesc}</P>
              </Section>
            </Card>

            {/* Watchlist Star */}
            <Card>
              <Section title={h.watchlistStarTitle}>
                <P>{h.watchlistStarDesc}</P>
              </Section>
            </Card>

            {/* Watchlist Alerts */}
            <Card>
              <Section title={h.watchlistAlertsTitle}>
                <P>{h.watchlistAlertsDesc}</P>
              </Section>
            </Card>
          </>
        )}

        {activeTab === 'brainAi' && (
          <>
            {/* Brain */}
            <Card>
              <Section title={h.brainTitle}>
                <P>{h.brainDesc}</P>
              </Section>
            </Card>

            {/* Brain Suggestions */}
            <Card>
              <Section title={h.selfLearningTitle}>
                <P>{h.selfLearningDesc}</P>
              </Section>
            </Card>

            {/* AI Providers */}
            <Card>
              <Section title={h.aiProvidersTitle}>
                <P>{h.aiProvidersDesc}</P>
                <ul className="space-y-1.5 mt-2">
                  <Li>{h.aiProvider1}</Li>
                  <Li>{h.aiProvider2}</Li>
                  <Li>{h.aiProvider3}</Li>
                </ul>
                <div className="mt-3">
                  <P>{h.aiProviderNote}</P>
                </div>
              </Section>
            </Card>

            {/* Two-Pass Scanning */}
            <Card>
              <Section title={h.twoPassTitle}>
                <P>{h.twoPassDesc}</P>
              </Section>
            </Card>

            {/* Market Regime Badges */}
            <Card>
              <Section title={h.regimeBadgesTitle}>
                <P>{h.regimeBadgesDesc}</P>
                <ul className="space-y-1.5 mt-2">
                  <Li>{h.regimeTrending}</Li>
                  <Li>{h.regimeVolatile}</Li>
                  <Li>{h.regimeCrisis}</Li>
                  <Li>{h.regimeRecovery}</Li>
                </ul>
              </Section>
            </Card>

            {/* Kelly Position Sizing */}
            <Card>
              <Section title={h.kellyTitle}>
                <P>{h.kellyDesc}</P>
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

            {/* Brain Rules & Mechanism */}
            <Card>
              <Section title={h.brainRulesTitle}>
                <P>{h.brainRulesIntro}</P>

                <div className="mt-4">
                  <h3 className="text-sm font-semibold mb-2" style={{ color: theme.colors.text }}>
                    {h.brainTieredTitle}
                  </h3>
                  <P>{h.brainTieredDesc}</P>
                  <ul className="space-y-1.5 mt-2">
                    <Li>{h.brainTier1}</Li>
                    <Li>{h.brainTier2}</Li>
                    <Li>{h.brainTier3}</Li>
                    <Li>{h.brainTierFailed}</Li>
                  </ul>
                </div>

                <div className="mt-4">
                  <h3 className="text-sm font-semibold mb-2" style={{ color: theme.colors.text }}>
                    {h.brainMarketHoursTitle}
                  </h3>
                  <P>{h.brainMarketHoursDesc}</P>
                </div>

                <div className="mt-4">
                  <h3 className="text-sm font-semibold mb-2" style={{ color: theme.colors.text }}>
                    {h.brainPreMarketReviewTitle}
                  </h3>
                  <P>{h.brainPreMarketReviewDesc}</P>
                  <ul className="space-y-1.5 mt-2">
                    <Li>{h.brainReviewFlow1}</Li>
                    <Li>{h.brainReviewFlow2}</Li>
                    <Li>{h.brainReviewFlow3}</Li>
                    <Li>{h.brainReviewFlow4}</Li>
                  </ul>
                </div>

                <div className="mt-4">
                  <h3 className="text-sm font-semibold mb-2" style={{ color: theme.colors.text }}>
                    {h.brainTelegramCommandsTitle}
                  </h3>
                  <P>{h.brainTelegramCommandsDesc}</P>
                  <ul className="space-y-1.5 mt-2">
                    <Li>{h.brainCmd1}</Li>
                    <Li>{h.brainCmd2}</Li>
                    <Li>{h.brainCmd3}</Li>
                  </ul>
                </div>

                <div className="mt-4">
                  <h3 className="text-sm font-semibold mb-2" style={{ color: theme.colors.text }}>
                    {h.brainAIChainTitle}
                  </h3>
                  <P>{h.brainAIChainDesc}</P>
                  <ul className="space-y-1.5 mt-2">
                    <Li>{h.brainAIChain1}</Li>
                    <Li>{h.brainAIChain2}</Li>
                    <Li>{h.brainAIChain3}</Li>
                    <Li>{h.brainAIChain4}</Li>
                  </ul>
                </div>

                <div className="mt-4">
                  <h3 className="text-sm font-semibold mb-2" style={{ color: theme.colors.text }}>
                    {h.brainAlertsTitle}
                  </h3>
                  <P>{h.brainAlertsDesc}</P>
                  <ul className="space-y-1.5 mt-2">
                    <Li>{h.brainAlert1}</Li>
                    <Li>{h.brainAlert2}</Li>
                    <Li>{h.brainAlert3}</Li>
                  </ul>
                </div>

                <div className="mt-4">
                  <h3 className="text-sm font-semibold mb-2" style={{ color: theme.colors.text }}>
                    {h.brainScoreDropGuardTitle}
                  </h3>
                  <P>{h.brainScoreDropGuardDesc}</P>
                </div>
              </Section>
            </Card>

            {/* Trade Horizon: SHORT vs LONG */}
            <Card>
              <Section title={h.horizonTitle}>
                <P>{h.horizonDesc}</P>
                <div className="space-y-2 mt-2">
                  <Step title={h.horizonShortTitle} desc={h.horizonShortDesc} />
                  <Step title={h.horizonLongTitle} desc={h.horizonLongDesc} />
                </div>
                <div className="mt-3">
                  <P>{h.horizonClassification}</P>
                </div>
                <div className="mt-3">
                  <P>{h.horizonWhy}</P>
                </div>
              </Section>
            </Card>

            {/* Two-Wallet System */}
            <Card>
              <Section title={h.twoWalletTitle}>
                <P>{h.twoWalletDesc}</P>
                <div className="space-y-2 mt-2">
                  <Step title={h.twoWalletLongTitle} desc={h.twoWalletLongDesc} />
                  <Step title={h.twoWalletShortTitle} desc={h.twoWalletShortDesc} />
                </div>
                <div className="mt-3">
                  <P>{h.twoWalletNote}</P>
                </div>
              </Section>
            </Card>

            {/* Virtual Portfolio */}
            <Card>
              <Section title={h.virtualPortfolioTitle}>
                <P>{h.virtualPortfolioDesc}</P>
                <ul className="space-y-1.5 mt-2">
                  <Li>{h.vp1}</Li>
                  <Li>{h.vp2}</Li>
                  <Li>{h.vp3}</Li>
                  <Li>{h.vp4}</Li>
                  <Li>{h.vp5}</Li>
                  <Li>{h.vp6}</Li>
                </ul>
                <div className="mt-3">
                  <P>{h.vpNote}</P>
                </div>
              </Section>
            </Card>

            {/* Brain Watchdog */}
            <Card>
              <Section title={h.watchdogTitle}>
                <P>{h.watchdogDesc}</P>
                <ul className="space-y-1.5 mt-2">
                  <Li>{h.wd1}</Li>
                  <Li>{h.wd2}</Li>
                  <Li>{h.wd3}</Li>
                  <Li>{h.wd4}</Li>
                  <Li>{h.wd5}</Li>
                  <Li>{h.wd6}</Li>
                </ul>
                <div className="mt-3">
                  <P>{h.wdNote}</P>
                </div>
              </Section>
            </Card>

            {/* Watchdog Cooldown */}
            <Card>
              <Section title={h.wdCooldownTitle}>
                <P>{h.wdCooldownDesc}</P>
              </Section>
            </Card>

            {/* Watchdog Event Types */}
            <Card>
              <Section title={h.wdEventsTitle}>
                <P>{h.wdEventsDesc}</P>
                <ul className="space-y-1.5 mt-2">
                  <Li>{h.wdEventAlert}</Li>
                  <Li>{h.wdEventEscalation}</Li>
                  <Li>{h.wdEventHold}</Li>
                  <Li>{h.wdEventClose}</Li>
                  <Li>{h.wdEventRecovery}</Li>
                </ul>
              </Section>
            </Card>

            {/* Self-Learning Loop */}
            <Card>
              <Section title={h.learningLoopTitle}>
                <P>{h.learningLoopDesc}</P>

                <div className="mt-4">
                  <h3 className="text-sm font-semibold mb-2" style={{ color: theme.colors.text }}>
                    {h.learningPrincipleTitle}
                  </h3>
                  <P>{h.learningPrincipleDesc}</P>
                </div>

                <div className="mt-4">
                  <h3 className="text-sm font-semibold mb-2" style={{ color: theme.colors.text }}>
                    {h.learningLayersTitle}
                  </h3>
                  <P>{h.learningLayersDesc}</P>
                  <ul className="space-y-1.5 mt-2">
                    <Li>{h.learningLayer1}</Li>
                    <Li>{h.learningLayer2}</Li>
                    <Li>{h.learningLayer3}</Li>
                    <Li>{h.learningLayer4}</Li>
                  </ul>
                </div>

                <div className="mt-4">
                  <h3 className="text-sm font-semibold mb-2" style={{ color: theme.colors.text }}>
                    {h.thinkingVsKnowledgeTitle}
                  </h3>
                  <P>{h.thinkingVsKnowledgeDesc}</P>
                </div>

                <div className="mt-4">
                  <h3 className="text-sm font-semibold mb-2" style={{ color: theme.colors.text }}>
                    {h.thesisTrackingTitle}
                  </h3>
                  <P>{h.thesisTrackingDesc}</P>
                </div>

                <div className="mt-4">
                  <h3 className="text-sm font-semibold mb-2" style={{ color: theme.colors.text }}>
                    {h.thesisInvalidatedTitle}
                  </h3>
                  <P>{h.thesisInvalidatedDesc}</P>
                  <div className="mt-2">
                    <P>{h.thesisInvalidatedExample}</P>
                  </div>
                </div>

                <div className="mt-4">
                  <h3 className="text-sm font-semibold mb-2" style={{ color: theme.colors.text }}>
                    {h.thesisGateTitle}
                  </h3>
                  <P>{h.thesisGateDesc}</P>
                </div>

                <div className="mt-4">
                  <h3 className="text-sm font-semibold mb-2" style={{ color: theme.colors.text }}>
                    {h.learningAuditTitle}
                  </h3>
                  <P>{h.learningAuditDesc}</P>
                </div>

                <div className="mt-4">
                  <h3 className="text-sm font-semibold mb-2" style={{ color: theme.colors.text }}>
                    {h.thesisDotsTitle}
                  </h3>
                  <P>{h.thesisDotsDesc}</P>
                </div>

                <div className="mt-4">
                  <h3 className="text-sm font-semibold mb-2" style={{ color: theme.colors.text }}>
                    {h.rebuyCooldownTitle}
                  </h3>
                  <P>{h.rebuyCooldownDesc}</P>
                </div>

                <div className="mt-4">
                  <h3 className="text-sm font-semibold mb-2" style={{ color: theme.colors.text }}>
                    {h.trailingStopTitle}
                  </h3>
                  <P>{h.trailingStopDesc}</P>
                </div>

                <div className="mt-4">
                  <h3 className="text-sm font-semibold mb-2" style={{ color: theme.colors.text }}>
                    {h.sma50FilterTitle}
                  </h3>
                  <P>{h.sma50FilterDesc}</P>
                </div>

                <div className="mt-4">
                  <h3 className="text-sm font-semibold mb-2" style={{ color: theme.colors.text }}>
                    {h.shortInterestSignalsTitle}
                  </h3>
                  <P>{h.shortInterestSignalsDesc}</P>
                </div>

                <div className="mt-4">
                  <h3 className="text-sm font-semibold mb-2" style={{ color: theme.colors.text }}>
                    {h.exitLabelsTitle}
                  </h3>
                  <P>{h.exitLabelsDesc}</P>
                </div>
              </Section>
            </Card>

            {/* Fear & Greed Index */}
            <Card>
              <Section title={h.fearGreedTitle}>
                <P>{h.fearGreedDesc}</P>
              </Section>
            </Card>

            {/* Macro Environment Badge */}
            {h.macroEnvironmentTitle && (
              <Card>
                <Section title={h.macroEnvironmentTitle}>
                  <P>{h.macroEnvironmentDesc}</P>
                </Section>
              </Card>
            )}

            {/* Intermarket Indicators */}
            <Card>
              <Section title={h.intermarketTitle}>
                <P>{h.intermarketDesc}</P>
                <ul className="space-y-1.5 mt-2">
                  <Li>{h.intermarket1}</Li>
                  <Li>{h.intermarket2}</Li>
                  <Li>{h.intermarket3}</Li>
                </ul>
              </Section>
            </Card>

            {/* Yield Curve */}
            <Card>
              <Section title={h.yieldCurveTitle}>
                <P>{h.yieldCurveDesc}</P>
              </Section>
            </Card>

            {/* Credit Spreads */}
            <Card>
              <Section title={h.creditSpreadTitle}>
                <P>{h.creditSpreadDesc}</P>
              </Section>
            </Card>

            {/* VIX Term Structure */}
            <Card>
              <Section title={h.vixTermTitle}>
                <P>{h.vixTermDesc}</P>
              </Section>
            </Card>

            {/* Macro Warning Signs */}
            <Card>
              <Section title={h.warningSignsTitle}>
                <P>{h.warningSignsDesc}</P>
                <ul className="space-y-1.5 mt-2">
                  <Li>{h.warning1}</Li>
                  <Li>{h.warning2}</Li>
                  <Li>{h.warning3}</Li>
                </ul>
              </Section>
            </Card>

            {/* RECOVERY Regime */}
            <Card>
              <Section title={h.recoveryRegimeTitle}>
                <P>{h.recoveryRegimeDesc}</P>
              </Section>
            </Card>

            {/* Probability vs SPY */}
            <Card>
              <Section title={h.probVsSpyTitle}>
                <P>{h.probVsSpyDesc}</P>
              </Section>
            </Card>

            {/* Factor Impact Labels */}
            <Card>
              <Section title={h.factorLabelsTitle}>
                <P>{h.factorLabelsDesc}</P>
              </Section>
            </Card>

            {/* Short Interest */}
            <Card>
              <Section title={h.shortInterestTitle}>
                <P>{h.shortInterestDesc}</P>
              </Section>
            </Card>

            {/* Crypto Position Sizing */}
            <Card>
              <Section title={h.cryptoScalingTitle}>
                <P>{h.cryptoScalingDesc}</P>
              </Section>
            </Card>

            {/* Brain Radar */}
            <Card>
              <Section title={h.brainRadarTitle}>
                <P>{h.brainRadarDesc}</P>
              </Section>
            </Card>

            {/* Track Record */}
            <Card>
              <Section title={h.trackRecordTitle}>
                <P>{h.trackRecordDesc}</P>
              </Section>
            </Card>

            {/* AI Budget System */}
            <Card>
              <Section title={h.budgetSystemTitle}>
                <P>{h.budgetSystemDesc}</P>
                <ul className="space-y-1.5 mt-2">
                  <Li>{h.budget1}</Li>
                  <Li>{h.budget2}</Li>
                  <Li>{h.budget3}</Li>
                  <Li>{h.budget4}</Li>
                  <Li>{h.budget5}</Li>
                  <Li>{h.budget6}</Li>
                </ul>
                <div className="mt-3">
                  <P>{h.budgetNote}</P>
                </div>
              </Section>
            </Card>
          </>
        )}

        {activeTab === 'accountsSetup' && (
          <>
            {/* Canadian Account Types */}
            <Card>
              <Section title={h.accountsTitle}>
                <P>{h.accountsDesc}</P>
                <ul className="space-y-1.5 mt-2">
                  <Li>{h.account1}</Li>
                  <Li>{h.account2}</Li>
                  <Li>{h.account3}</Li>
                </ul>
              </Section>
            </Card>

            {/* Account Recommendation Badges */}
            <Card>
              <Section title={h.accountBadgesTitle}>
                <P>{h.accountBadgesDesc}</P>
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

            {/* Telegram Message Types */}
            <Card>
              <Section title={h.telegramMsgsTitle}>
                <P>{h.telegramMsgsDesc}</P>
                <ul className="space-y-1.5 mt-2">
                  <Li>{h.tgMsg1}</Li>
                  <Li>{h.tgMsg2}</Li>
                  <Li>{h.tgMsg3}</Li>
                  <Li>{h.tgMsg4}</Li>
                  <Li>{h.tgMsg5}</Li>
                  <Li>{h.tgMsg6}</Li>
                </ul>
                <div className="mt-3">
                  <P>{h.tgMsgNote}</P>
                </div>
              </Section>
            </Card>

            {/* How Notifications Work */}
            <Card>
              <Section title={h.notificationsTitle}>
                <P>{h.notificationsDesc}</P>
                <ul className="space-y-1.5 mt-2">
                  <Li>{h.notif1}</Li>
                  <Li>{h.notif2}</Li>
                  <Li>{h.notif3}</Li>
                  <Li>{h.notif4}</Li>
                  <Li>{h.notif5}</Li>
                  <Li>{h.notif6}</Li>
                  <Li>{h.notif7}</Li>
                  <Li>{h.notif8}</Li>
                </ul>
                <div className="mt-3">
                  <P>{h.notifNote}</P>
                </div>
              </Section>
            </Card>

            {/* Risk Levels */}
            <Card>
              <Section title={h.riskLevelsTitle}>
                <P>{h.riskLevelsDesc}</P>
                <ul className="space-y-1.5 mt-2">
                  <Li>{h.riskLow}</Li>
                  <Li>{h.riskMed}</Li>
                  <Li>{h.riskHigh}</Li>
                </ul>
              </Section>
            </Card>

            {/* Integrations Page */}
            <Card>
              <Section title={h.integrationsPageTitle}>
                <P>{h.integrationsPageDesc}</P>
              </Section>
            </Card>

            {/* Logs Page */}
            <Card>
              <Section title={h.logsPageTitle}>
                <P>{h.logsPageDesc}</P>
              </Section>
            </Card>

            {/* Settings */}
            <Card>
              <Section title={h.settingsTitle}>
                <P>{h.settingsDesc}</P>
              </Section>
            </Card>

            {/* Themes */}
            <Card>
              <Section title={h.themesTitle}>
                <P>{h.themesDesc}</P>
              </Section>
            </Card>

            {/* OTP Paste */}
            <Card>
              <Section title={h.otpPasteTitle}>
                <P>{h.otpPasteDesc}</P>
              </Section>
            </Card>
          </>
        )}

        {activeTab === 'reference' && (
          <>
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

            {/* Glossary */}
            <Card>
              <Section title={h.glossaryTitle}>
                <P>{h.glossaryDesc}</P>
                <div className="mt-3 space-y-2">
                  {(h.glossary as Array<{ term: string; meaning: string }>).map((item) => (
                    <div key={item.term} className="flex gap-3 py-1" style={{ borderBottom: `1px solid ${theme.colors.border}20` }}>
                      <span className="text-xs font-bold w-16 shrink-0 tabular-nums" style={{ color: theme.colors.primary }}>
                        {item.term}
                      </span>
                      <span className="text-xs leading-relaxed" style={{ color: theme.colors.textSub }}>
                        {item.meaning}
                      </span>
                    </div>
                  ))}
                </div>
              </Section>
            </Card>
          </>
        )}
      </div>
    </div>
  )
}
