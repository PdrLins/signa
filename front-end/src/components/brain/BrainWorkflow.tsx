'use client'

import { useState } from 'react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'

interface StepNode {
  id: string
  label: string
  sub: string
  icon: string
  color: 'primary' | 'up' | 'down' | 'warning' | 'text'
  group: 'input' | 'analysis' | 'decision' | 'output'
  detail: string
  ruleType?: string // maps to investment_rules.rule_type for "View rules" link
}

function useSteps(): StepNode[] {
  const b = useI18nStore((s) => s.t).brain
  return [
    { id: 'universe', label: b.wfUniverseLabel, sub: b.wfUniverseSub, icon: '🌐', color: 'text', group: 'input', detail: b.wfUniverseDetail },
    { id: 'prefilter', label: b.wfPrefilterLabel, sub: b.wfPrefilterSub, icon: '🔍', color: 'text', group: 'input', detail: b.wfPrefilterDetail, ruleType: 'SOLVENCY' },
    { id: 'regime', label: b.wfRegimeLabel, sub: b.wfRegimeSub, icon: '🌡️', color: 'warning', group: 'input', detail: b.wfRegimeDetail },
    { id: 'technicals', label: b.wfTechnicalsLabel, sub: b.wfTechnicalsSub, icon: '📊', color: 'primary', group: 'analysis', detail: b.wfTechnicalsDetail, ruleType: 'TECHNICAL' },
    { id: 'fundamentals', label: b.wfFundamentalsLabel, sub: b.wfFundamentalsSub, icon: '📋', color: 'primary', group: 'analysis', detail: b.wfFundamentalsDetail, ruleType: 'FUNDAMENTAL' },
    { id: 'macro', label: b.wfMacroLabel, sub: b.wfMacroSub, icon: '🏛️', color: 'primary', group: 'analysis', detail: b.wfMacroDetail },
    { id: 'sentiment', label: b.wfSentimentLabel, sub: b.wfSentimentSub, icon: '🐦', color: 'primary', group: 'analysis', detail: b.wfSentimentDetail },
    { id: 'synthesis', label: b.wfSynthesisLabel, sub: b.wfSynthesisSub, icon: '🧠', color: 'primary', group: 'analysis', detail: b.wfSynthesisDetail },
    { id: 'scoring', label: b.wfScoringLabel, sub: b.wfScoringSub, icon: '⚖️', color: 'up', group: 'decision', detail: b.wfScoringDetail },
    { id: 'blockers', label: b.wfBlockersLabel, sub: b.wfBlockersSub, icon: '🚫', color: 'down', group: 'decision', detail: b.wfBlockersDetail, ruleType: 'SOLVENCY' },
    { id: 'action', label: b.wfActionLabel, sub: b.wfActionSub, icon: '🎯', color: 'up', group: 'decision', detail: b.wfActionDetail },
    { id: 'gem', label: b.wfGemLabel, sub: b.wfGemSub, icon: '💎', color: 'up', group: 'decision', detail: b.wfGemDetail },
    { id: 'kelly', label: b.wfKellyLabel, sub: b.wfKellySub, icon: '📐', color: 'warning', group: 'output', detail: b.wfKellyDetail, ruleType: 'KELLY' },
    { id: 'signal', label: b.wfSignalLabel, sub: b.wfSignalSub, icon: '📡', color: 'up', group: 'output', detail: b.wfSignalDetail },
    { id: 'telegram', label: b.wfAlertsLabel, sub: b.wfAlertsSub, icon: '🔔', color: 'warning', group: 'output', detail: b.wfAlertsDetail },
  ]
}


function StepCard({ step, index, total, unlocked = false, onViewRules }: {
  step: StepNode; index: number; total: number; unlocked?: boolean
  onViewRules?: (ruleType: string) => void
}) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const [hovered, setHovered] = useState(false)
  const colorMap: Record<string, string> = {
    primary: theme.colors.primary,
    up: theme.colors.up,
    down: theme.colors.down,
    warning: theme.colors.warning,
    text: theme.colors.textSub,
  }
  const accent = colorMap[step.color]
  const isLast = index === total - 1

  return (
    <div
      className="flex items-start gap-3"
      onMouseEnter={() => unlocked && setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {/* Vertical connector */}
      <div className="flex flex-col items-center w-8 shrink-0">
        <div
          className="w-8 h-8 rounded-lg flex items-center justify-center text-sm shrink-0 transition-transform"
          style={{
            backgroundColor: accent + (hovered ? '25' : '15'),
            border: `1.5px solid ${accent}${hovered ? '80' : '40'}`,
            transform: hovered ? 'scale(1.1)' : 'none',
          }}
        >
          {step.icon}
        </div>
        {!isLast && (
          <div className="w-px flex-1 min-h-[20px]" style={{ backgroundColor: theme.colors.border }} />
        )}
      </div>

      {/* Content */}
      <div className="pb-4 flex-1 min-w-0">
        <p className="text-sm font-semibold leading-tight" style={{ color: theme.colors.text }}>
          {step.label}
        </p>
        <p className="text-[11px] mt-0.5" style={{ color: theme.colors.textSub }}>
          {step.sub}
        </p>

        {/* Detail panel — only visible on hover when unlocked */}
        {hovered && unlocked && (
          <div
            className="mt-2 rounded-lg px-3 py-2 text-[11px] leading-relaxed"
            style={{ backgroundColor: theme.colors.surface, border: `1px solid ${accent}30`, color: theme.colors.textSub }}
          >
            {step.detail}
            {step.ruleType && onViewRules && (
              <button
                className="block mt-1.5 text-[10px] font-semibold underline"
                style={{ color: accent }}
                onClick={() => onViewRules(step.ruleType!)}
              >
                {t.brain.viewRelatedRules} →
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export function BrainWorkflow({ compact = false, unlocked = false, onViewRules }: {
  compact?: boolean
  unlocked?: boolean
  onViewRules?: (ruleType: string) => void
}) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const steps_ = useSteps()

  const groupLabels: Record<string, string> = {
    input: t.brain.wfDataCollection,
    analysis: t.brain.wfAnalysis,
    decision: t.brain.wfDecision,
    output: t.brain.wfOutput,
  }
  const groups = compact
    ? { all: steps_ }
    : {
        input: steps_.filter((s) => s.group === 'input'),
        analysis: steps_.filter((s) => s.group === 'analysis'),
        decision: steps_.filter((s) => s.group === 'decision'),
        output: steps_.filter((s) => s.group === 'output'),
      }

  if (compact) {
    return (
      <div>
        {steps_.map((step, i) => (
          <StepCard key={step.id} step={step} index={i} total={steps_.length} unlocked={unlocked} onViewRules={onViewRules} />
        ))}
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {Object.entries(groups).map(([groupKey, steps]) => (
        <div key={groupKey}>
          <div className="flex items-center gap-2 mb-3">
            <div className="h-px flex-1" style={{ backgroundColor: theme.colors.border }} />
            <span
              className="text-[9px] font-bold uppercase tracking-widest px-2"
              style={{ color: theme.colors.textHint }}
            >
              {groupLabels[groupKey] || groupKey}
            </span>
            <div className="h-px flex-1" style={{ backgroundColor: theme.colors.border }} />
          </div>
          {steps.map((step: StepNode, i: number) => (
            <StepCard key={step.id} step={step} index={i} total={steps.length} unlocked={unlocked} onViewRules={onViewRules} />
          ))}
        </div>
      ))}

      {/* Scoring weights breakdown */}
      <div>
        <div className="flex items-center gap-2 mb-3">
          <div className="h-px flex-1" style={{ backgroundColor: theme.colors.border }} />
          <span className="text-[9px] font-bold uppercase tracking-widest px-2" style={{ color: theme.colors.textHint }}>
            {t.brain.wfScoringWeights}
          </span>
          <div className="h-px flex-1" style={{ backgroundColor: theme.colors.border }} />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div className="rounded-xl p-3" style={{ backgroundColor: theme.colors.up + '08', border: `1px solid ${theme.colors.up}20` }}>
            <p className="text-xs font-bold mb-2" style={{ color: theme.colors.up }}>{t.brain.wfSafeIncome}</p>
            {[
              { label: t.brain.wfDividendReliability, pct: 35 },
              { label: t.brain.wfFundamentalHealth, pct: 30 },
              { label: t.brain.wfMacroConditions, pct: 25 },
              { label: t.brain.wfSentiment, pct: 10 },
            ].map((w) => (
              <div key={w.label} className="flex items-center justify-between py-0.5">
                <span className="text-[10px]" style={{ color: theme.colors.textSub }}>{w.label}</span>
                <span className="text-[10px] font-bold tabular-nums" style={{ color: theme.colors.up }}>{w.pct}%</span>
              </div>
            ))}
          </div>
          <div className="rounded-xl p-3" style={{ backgroundColor: theme.colors.primary + '08', border: `1px solid ${theme.colors.primary}20` }}>
            <p className="text-xs font-bold mb-2" style={{ color: theme.colors.primary }}>{t.brain.wfHighRisk}</p>
            {[
              { label: t.brain.wfXTwitterSentiment, pct: 35 },
              { label: t.brain.wfCatalystDetection, pct: 30 },
              { label: t.brain.wfTechnicalMomentum, pct: 25 },
              { label: t.brain.wfFundamentals, pct: 10 },
            ].map((w) => (
              <div key={w.label} className="flex items-center justify-between py-0.5">
                <span className="text-[10px]" style={{ color: theme.colors.textSub }}>{w.label}</span>
                <span className="text-[10px] font-bold tabular-nums" style={{ color: theme.colors.primary }}>{w.pct}%</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Regime behavior */}
      <div>
        <div className="flex items-center gap-2 mb-3">
          <div className="h-px flex-1" style={{ backgroundColor: theme.colors.border }} />
          <span className="text-[9px] font-bold uppercase tracking-widest px-2" style={{ color: theme.colors.textHint }}>
            {t.brain.wfMarketRegimes}
          </span>
          <div className="h-px flex-1" style={{ backgroundColor: theme.colors.border }} />
        </div>
        <div className="space-y-2">
          {[
            { regime: 'TRENDING', vix: 'VIX < 20', desc: t.brain.wfFullSignals, color: theme.colors.up },
            { regime: 'VOLATILE', vix: 'VIX 20-30', desc: t.brain.wfReducedSignals, color: theme.colors.warning },
            { regime: 'CRISIS', vix: 'VIX > 30', desc: t.brain.wfPausedSignals, color: theme.colors.down },
          ].map((r) => (
            <div key={r.regime} className="flex items-center gap-3 rounded-lg px-3 py-2" style={{ backgroundColor: r.color + '08', border: `1px solid ${r.color}20` }}>
              <span className="text-xs font-bold w-20" style={{ color: r.color }}>{r.regime}</span>
              <span className="text-[10px] w-16 tabular-nums" style={{ color: theme.colors.textSub }}>{r.vix}</span>
              <span className="text-[10px] flex-1" style={{ color: theme.colors.textSub }}>{r.desc}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
