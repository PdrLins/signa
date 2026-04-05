'use client'

import { useTheme } from '@/hooks/useTheme'

interface StepNode {
  id: string
  label: string
  sub: string
  icon: string
  color: 'primary' | 'up' | 'down' | 'warning' | 'text'
  group: 'input' | 'analysis' | 'decision' | 'output'
}

const STEPS: StepNode[] = [
  // Input
  { id: 'universe', label: 'Universe', sub: '188 tickers', icon: '🌐', color: 'text', group: 'input' },
  { id: 'prefilter', label: 'Pre-filter', sub: 'Top 50 candidates', icon: '🔍', color: 'text', group: 'input' },
  { id: 'regime', label: 'Regime Check', sub: 'TRENDING / VOLATILE / CRISIS', icon: '🌡️', color: 'warning', group: 'input' },

  // Analysis (per ticker)
  { id: 'technicals', label: 'Technicals', sub: 'RSI, MACD, SMA, Volume', icon: '📊', color: 'primary', group: 'analysis' },
  { id: 'fundamentals', label: 'Fundamentals', sub: 'P/E, EPS, Dividends', icon: '📋', color: 'primary', group: 'analysis' },
  { id: 'macro', label: 'Macro', sub: 'FRED: Rates, CPI, VIX', icon: '🏛️', color: 'primary', group: 'analysis' },
  { id: 'sentiment', label: 'Sentiment', sub: 'Grok / Gemini X/Twitter', icon: '🐦', color: 'primary', group: 'analysis' },
  { id: 'synthesis', label: 'AI Synthesis', sub: 'Claude / Gemini', icon: '🧠', color: 'primary', group: 'analysis' },

  // Decision
  { id: 'scoring', label: '5-Layer Score', sub: 'Weighted 0-100', icon: '⚖️', color: 'up', group: 'decision' },
  { id: 'blockers', label: 'Blockers', sub: 'RSI>75, VIX, Fraud', icon: '🚫', color: 'down', group: 'decision' },
  { id: 'action', label: 'Action', sub: 'BUY / HOLD / SELL / AVOID', icon: '🎯', color: 'up', group: 'decision' },
  { id: 'gem', label: 'GEM Check', sub: '5 conditions required', icon: '💎', color: 'up', group: 'decision' },

  // Output
  { id: 'kelly', label: 'Kelly Sizing', sub: 'Position % recommendation', icon: '📐', color: 'warning', group: 'output' },
  { id: 'signal', label: 'Signal', sub: 'Stored + displayed', icon: '📡', color: 'up', group: 'output' },
  { id: 'telegram', label: 'Alerts', sub: 'Telegram notifications', icon: '🔔', color: 'warning', group: 'output' },
]

const GROUP_LABELS: Record<string, string> = {
  input: 'DATA COLLECTION',
  analysis: 'PER-TICKER ANALYSIS',
  decision: 'DECISION ENGINE',
  output: 'OUTPUT',
}

function StepCard({ step, index, total }: { step: StepNode; index: number; total: number }) {
  const theme = useTheme()
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
    <div className="flex items-start gap-3">
      {/* Vertical connector */}
      <div className="flex flex-col items-center w-8 shrink-0">
        <div
          className="w-8 h-8 rounded-lg flex items-center justify-center text-sm shrink-0"
          style={{ backgroundColor: accent + '15', border: `1.5px solid ${accent}40` }}
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
      </div>
    </div>
  )
}

export function BrainWorkflow({ compact = false }: { compact?: boolean }) {
  const theme = useTheme()
  const groups = compact
    ? { all: STEPS }
    : {
        input: STEPS.filter((s) => s.group === 'input'),
        analysis: STEPS.filter((s) => s.group === 'analysis'),
        decision: STEPS.filter((s) => s.group === 'decision'),
        output: STEPS.filter((s) => s.group === 'output'),
      }

  if (compact) {
    return (
      <div>
        {STEPS.map((step, i) => (
          <StepCard key={step.id} step={step} index={i} total={STEPS.length} />
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
              {GROUP_LABELS[groupKey] || groupKey}
            </span>
            <div className="h-px flex-1" style={{ backgroundColor: theme.colors.border }} />
          </div>
          {steps.map((step: StepNode, i: number) => (
            <StepCard key={step.id} step={step} index={i} total={steps.length} />
          ))}
        </div>
      ))}

      {/* Scoring weights breakdown */}
      <div>
        <div className="flex items-center gap-2 mb-3">
          <div className="h-px flex-1" style={{ backgroundColor: theme.colors.border }} />
          <span className="text-[9px] font-bold uppercase tracking-widest px-2" style={{ color: theme.colors.textHint }}>
            SCORING WEIGHTS
          </span>
          <div className="h-px flex-1" style={{ backgroundColor: theme.colors.border }} />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div className="rounded-xl p-3" style={{ backgroundColor: theme.colors.up + '08', border: `1px solid ${theme.colors.up}20` }}>
            <p className="text-xs font-bold mb-2" style={{ color: theme.colors.up }}>Safe Income</p>
            {[
              { label: 'Dividend reliability', pct: 35 },
              { label: 'Fundamental health', pct: 30 },
              { label: 'Macro conditions', pct: 25 },
              { label: 'Sentiment', pct: 10 },
            ].map((w) => (
              <div key={w.label} className="flex items-center justify-between py-0.5">
                <span className="text-[10px]" style={{ color: theme.colors.textSub }}>{w.label}</span>
                <span className="text-[10px] font-bold tabular-nums" style={{ color: theme.colors.up }}>{w.pct}%</span>
              </div>
            ))}
          </div>
          <div className="rounded-xl p-3" style={{ backgroundColor: theme.colors.primary + '08', border: `1px solid ${theme.colors.primary}20` }}>
            <p className="text-xs font-bold mb-2" style={{ color: theme.colors.primary }}>High Risk</p>
            {[
              { label: 'X/Twitter sentiment', pct: 35 },
              { label: 'Catalyst detection', pct: 30 },
              { label: 'Technical momentum', pct: 25 },
              { label: 'Fundamentals', pct: 10 },
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
            MARKET REGIMES
          </span>
          <div className="h-px flex-1" style={{ backgroundColor: theme.colors.border }} />
        </div>
        <div className="space-y-2">
          {[
            { regime: 'TRENDING', vix: 'VIX < 20', desc: 'Full signal generation. Normal Kelly sizing.', color: theme.colors.up },
            { regime: 'VOLATILE', vix: 'VIX 20-30', desc: 'High Risk scores reduced 15%. Kelly halved.', color: theme.colors.warning },
            { regime: 'CRISIS', vix: 'VIX > 30', desc: 'High Risk paused. Safe Income dividends only. Kelly capped 5%.', color: theme.colors.down },
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
