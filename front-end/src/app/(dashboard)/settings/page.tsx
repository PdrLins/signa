'use client'

import { useState, useEffect, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useThemeStore } from '@/store/themeStore'
import { useAuthStore } from '@/store/authStore'
import { useToast } from '@/hooks/useToast'
import { useRouter } from 'next/navigation'
import { themes, type ThemeId } from '@/lib/themes'
import { client } from '@/lib/api'
import { Card } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Skeleton } from '@/components/ui/Skeleton'
import { Check, Brain, Zap, Sparkles, ChevronUp, ChevronDown } from 'lucide-react'

const themeIds = Object.keys(themes) as ThemeId[]

interface AIProviderConfig {
  synthesis: {
    providers: string[]
    claude_local?: boolean
    available: Record<string, { configured: boolean; model: string }>
  }
  sentiment: {
    providers: string[]
    available: Record<string, { configured: boolean; model: string }>
  }
  scanning?: {
    ai_enabled: boolean
    ai_candidate_limit: number
    max_candidates: number
  }
  thresholds?: {
    score_buy_safe: number
    score_buy_risk: number
    score_hold: number
  }
  watchdog?: {
    min_notify_pct: number
    pnl_alert_pct: number
    stop_proximity_pct: number
    brain_max_open: number
    notify_quiet_enabled: boolean
    notify_quiet_start: number
    notify_quiet_end: number
  }
}

const PROVIDER_META: Record<string, { name: string; icon: typeof Brain; color: string }> = {
  claude: { name: 'Claude', icon: Brain, color: '#D97706' },
  gemini: { name: 'Gemini', icon: Sparkles, color: '#4285F4' },
  grok: { name: 'Grok', icon: Zap, color: '#1DA1F2' },
}

function ProviderList({
  label,
  providers,
  available,
  onReorder,
  localProviders,
}: {
  label: string
  providers: string[]
  available: Record<string, { configured: boolean; model: string }>
  onReorder: (newOrder: string[]) => void
  localProviders?: Record<string, boolean>
}) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const [dragIdx, setDragIdx] = useState<number | null>(null)
  const [overIdx, setOverIdx] = useState<number | null>(null)

  const handleDragStart = (idx: number) => {
    setDragIdx(idx)
  }

  const handleDragOver = (e: React.DragEvent, idx: number) => {
    e.preventDefault()
    setOverIdx(idx)
  }

  const handleDrop = (idx: number) => {
    if (dragIdx === null || dragIdx === idx) {
      setDragIdx(null)
      setOverIdx(null)
      return
    }
    const copy = [...providers]
    const [moved] = copy.splice(dragIdx, 1)
    copy.splice(idx, 0, moved)
    onReorder(copy)
    setDragIdx(null)
    setOverIdx(null)
  }

  const handleDragEnd = () => {
    setDragIdx(null)
    setOverIdx(null)
  }

  const moveItem = (idx: number, direction: -1 | 1) => {
    const newIdx = idx + direction
    if (newIdx < 0 || newIdx >= providers.length) return
    const copy = [...providers]
    const [moved] = copy.splice(idx, 1)
    copy.splice(newIdx, 0, moved)
    onReorder(copy)
  }

  return (
    <div>
      <p className="text-[10px] uppercase tracking-wide mb-2" style={{ color: theme.colors.textHint }}>
        {label}
      </p>
      <div className="space-y-1.5">
        {providers.map((id, idx) => {
          const meta = PROVIDER_META[id] || { name: id, icon: Brain, color: '#999' }
          const info = available[id]
          const Icon = meta.icon
          const configured = info?.configured ?? false
          const isPrimary = idx === 0
          const isDragging = dragIdx === idx
          const isOver = overIdx === idx && dragIdx !== idx
          return (
            <div
              key={id}
              draggable
              onDragStart={() => handleDragStart(idx)}
              onDragOver={(e) => handleDragOver(e, idx)}
              onDrop={() => handleDrop(idx)}
              onDragEnd={handleDragEnd}
              className="flex items-center gap-3 rounded-xl px-3 py-2.5 transition-all cursor-grab active:cursor-grabbing"
              style={{
                backgroundColor: isPrimary ? theme.colors.primary + '08' : theme.colors.surfaceAlt,
                border: `1px solid ${isOver ? theme.colors.primary : isPrimary ? theme.colors.primary + '30' : theme.colors.border}`,
                opacity: isDragging ? 0.4 : configured ? 1 : 0.5,
                transform: isOver ? 'scale(1.02)' : 'none',
              }}
            >
              {/* Drag handle — desktop only */}
              <div className="hidden sm:flex flex-col gap-px" style={{ color: theme.colors.textHint }}>
                <span className="text-[8px] leading-none">⠿</span>
              </div>
              {/* Mobile up/down arrows */}
              <div className="flex sm:hidden flex-col gap-0.5">
                <button
                  onClick={() => moveItem(idx, -1)}
                  disabled={idx === 0}
                  className="p-0.5 rounded transition-opacity"
                  style={{ color: idx === 0 ? theme.colors.border : theme.colors.textHint }}
                >
                  <ChevronUp size={12} />
                </button>
                <button
                  onClick={() => moveItem(idx, 1)}
                  disabled={idx === providers.length - 1}
                  className="p-0.5 rounded transition-opacity"
                  style={{ color: idx === providers.length - 1 ? theme.colors.border : theme.colors.textHint }}
                >
                  <ChevronDown size={12} />
                </button>
              </div>
              <div
                className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0"
                style={{ backgroundColor: meta.color + '18' }}
              >
                <Icon size={14} style={{ color: meta.color }} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5">
                  <p className="text-sm font-medium" style={{ color: theme.colors.text }}>
                    {meta.name}
                  </p>
                  {localProviders?.[id] && (
                    <span
                      className="text-[8px] font-bold uppercase px-1.5 py-0.5 rounded"
                      style={{ backgroundColor: theme.colors.up + '18', color: theme.colors.up }}
                    >
                      Local
                    </span>
                  )}
                </div>
                <p className="text-[10px]" style={{ color: theme.colors.textSub }}>
                  {localProviders?.[id] ? 'CLI — $0 cost' : (info?.model || t.settings.notConfigured)} {!localProviders?.[id] && !configured ? t.settings.noApiKey : ''}
                </p>
              </div>
              <span
                className="text-[9px] font-bold px-1.5 py-0.5 rounded"
                style={{
                  backgroundColor: isPrimary ? theme.colors.primary + '18' : 'transparent',
                  color: isPrimary ? theme.colors.primary : theme.colors.textHint,
                }}
              >
                {isPrimary ? t.settings.primary : `${t.settings.fallback} ${idx}`}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default function SettingsPage() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const locale = useI18nStore((s) => s.locale)
  const setLocale = useI18nStore((s) => s.setLocale)
  const setTheme = useThemeStore((s) => s.setTheme)
  const logout = useAuthStore((s) => s.logout)
  const router = useRouter()
  const toast = useToast()

  const { data: aiConfig, isLoading: aiLoading } = useQuery<AIProviderConfig>({
    queryKey: ['ai-config'],
    queryFn: async () => {
      const res = await client.get<AIProviderConfig>('/health/ai-config')
      return res.data
    },
  })

  const [synthProviders, setSynthProviders] = useState<string[]>([])
  const [sentProviders, setSentProviders] = useState<string[]>([])
  const [aiEnabled, setAiEnabled] = useState(true)
  const [aiLimit, setAiLimit] = useState(15)
  const [maxCandidates, setMaxCandidates] = useState(50)
  const [scoreBuySafe, setScoreBuySafe] = useState(62)
  const [scoreBuyRisk, setScoreBuyRisk] = useState(65)
  const [scoreHold, setScoreHold] = useState(55)
  const [wdMinNotify, setWdMinNotify] = useState(0.5)
  const [wdPnlAlert, setWdPnlAlert] = useState(2.0)
  const [brainMaxOpen, setBrainMaxOpen] = useState(20)
  const [quietEnabled, setQuietEnabled] = useState(true)
  const [quietStart, setQuietStart] = useState(18)
  const [quietEnd, setQuietEnd] = useState(6)
  const [dirty, setDirty] = useState(false)
  const [confirmSave, setConfirmSave] = useState(false)

  useEffect(() => {
    if (aiConfig) {
      setSynthProviders(aiConfig.synthesis.providers)
      setSentProviders(aiConfig.sentiment.providers)
      if (aiConfig.scanning) {
        setAiEnabled(aiConfig.scanning.ai_enabled)
        setAiLimit(aiConfig.scanning.ai_candidate_limit)
        setMaxCandidates(aiConfig.scanning.max_candidates)
      }
      if (aiConfig.thresholds) {
        setScoreBuySafe(aiConfig.thresholds.score_buy_safe)
        setScoreBuyRisk(aiConfig.thresholds.score_buy_risk)
        setScoreHold(aiConfig.thresholds.score_hold)
      }
      if (aiConfig.watchdog) {
        setWdMinNotify(aiConfig.watchdog.min_notify_pct)
        setWdPnlAlert(aiConfig.watchdog.pnl_alert_pct)
        setBrainMaxOpen(aiConfig.watchdog.brain_max_open)
        setQuietEnabled(aiConfig.watchdog.notify_quiet_enabled)
        setQuietStart(aiConfig.watchdog.notify_quiet_start)
        setQuietEnd(aiConfig.watchdog.notify_quiet_end)
      }
    }
  }, [aiConfig])

  const handleSave = useCallback(async () => {
    try {
      await client.put('/health/ai-config', {
        synthesis_providers: synthProviders,
        sentiment_providers: sentProviders,
        ai_enabled: aiEnabled,
        ai_candidate_limit: aiLimit,
        max_candidates: maxCandidates,
        score_buy_safe: scoreBuySafe,
        score_buy_risk: scoreBuyRisk,
        score_hold: scoreHold,
        watchdog_min_notify_pct: wdMinNotify,
        watchdog_pnl_alert_pct: wdPnlAlert,
        brain_max_open: brainMaxOpen,
        notify_quiet_enabled: quietEnabled,
        notify_quiet_start: quietStart,
        notify_quiet_end: quietEnd,
      })
      toast.show(t.settings.configSaved, 'success')
      setDirty(false)
    } catch {
      toast.show(t.settings.configSaveFailed, 'error')
    }
  }, [synthProviders, sentProviders, aiEnabled, aiLimit, maxCandidates, scoreBuySafe, scoreBuyRisk, scoreHold, wdMinNotify, wdPnlAlert, brainMaxOpen, quietEnabled, quietStart, quietEnd, toast, t])

  const handleLogout = () => {
    logout()
    router.push('/login')
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: theme.colors.text }}>{t.settings.title}</h1>
          <p className="text-sm mt-1" style={{ color: theme.colors.textSub }}>{t.settings.subtitle}</p>
        </div>
        {dirty && !confirmSave && (
          <Button onClick={() => setConfirmSave(true)}>{t.settings.save}</Button>
        )}
        {confirmSave && (
          <div className="flex items-center gap-2 rounded-xl px-3 py-2" style={{ backgroundColor: theme.colors.warning + '12', border: `1px solid ${theme.colors.warning}40` }}>
            <p className="text-xs" style={{ color: theme.colors.text }}>
              {t.settings.confirmSaveMessage}
            </p>
            <button
              onClick={() => { handleSave(); setConfirmSave(false) }}
              className="text-xs font-semibold px-3 py-1.5 rounded-lg shrink-0 transition-opacity hover:opacity-80"
              style={{ backgroundColor: theme.colors.warning, color: theme.colors.surface }}
            >
              {t.settings.confirm}
            </button>
            <button
              onClick={() => setConfirmSave(false)}
              className="text-xs font-medium px-2 py-1.5 rounded-lg shrink-0 transition-opacity hover:opacity-80"
              style={{ color: theme.colors.textSub }}
            >
              {t.settings.cancel}
            </button>
          </div>
        )}
      </div>

      {/* AI Providers */}
      <Card>
        <div className="flex items-center justify-between mb-4">
          <p className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: theme.colors.textSub }}>
            {t.settings.aiProviders}
          </p>
        </div>

        {aiLoading ? (
          <Skeleton width="100%" height={120} />
        ) : aiConfig ? (
          <div className="space-y-5">
            <ProviderList
              label={t.settings.signalAnalysis}
              providers={synthProviders}
              available={aiConfig.synthesis.available}
              onReorder={(p) => { setSynthProviders(p); setDirty(true) }}
              localProviders={aiConfig.synthesis.claude_local ? { claude: true } : undefined}
            />
            <ProviderList
              label={t.settings.marketSentiment}
              providers={sentProviders}
              available={aiConfig.sentiment.available}
              onReorder={(p) => { setSentProviders(p); setDirty(true) }}
            />
          </div>
        ) : null}
        <p className="text-[10px] mt-3" style={{ color: theme.colors.textHint }}>
          {t.settings.dragHint}
        </p>
      </Card>

      {/* Scanning */}
      <Card>
        <div className="flex items-center justify-between mb-4">
          <p className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: theme.colors.textSub }}>
            {t.settings.scanning}
          </p>
        </div>
        <div className="space-y-4">
          {/* AI toggle */}
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium" style={{ color: theme.colors.text }}>{t.settings.aiAnalysis}</p>
              <p className="text-[10px]" style={{ color: theme.colors.textSub }}>
                {aiEnabled ? t.settings.aiAnalysisOnDesc : t.settings.aiAnalysisOffDesc}
              </p>
            </div>
            <button
              onClick={() => { setAiEnabled(!aiEnabled); setDirty(true) }}
              className="w-11 h-6 rounded-full transition-all relative"
              style={{ backgroundColor: aiEnabled ? theme.colors.primary : theme.colors.border }}
            >
              <div
                className="w-5 h-5 rounded-full bg-white absolute top-0.5 transition-all"
                style={{ left: aiEnabled ? 22 : 2 }}
              />
            </button>
          </div>

          {/* AI candidate limit */}
          {aiEnabled && (
            <div>
              <div className="flex items-center justify-between mb-1">
                <p className="text-sm font-medium" style={{ color: theme.colors.text }}>{t.settings.aiCandidates}</p>
                <span className="text-sm font-bold tabular-nums" style={{ color: theme.colors.primary }}>{aiLimit}</span>
              </div>
              <input
                type="range"
                min={5}
                max={50}
                value={aiLimit}
                onChange={(e) => { setAiLimit(Number(e.target.value)); setDirty(true) }}
                className="w-full"
              />
              <div className="flex justify-between">
                <span className="text-[9px]" style={{ color: theme.colors.textHint }}>5 ({t.settings.cheapest})</span>
                <span className="text-[9px]" style={{ color: theme.colors.textHint }}>50 ({t.settings.allGetAi})</span>
              </div>
            </div>
          )}

          {/* Max pre-filter candidates */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <p className="text-sm font-medium" style={{ color: theme.colors.text }}>{t.settings.preFilterCandidates}</p>
              <span className="text-sm font-bold tabular-nums" style={{ color: theme.colors.primary }}>{maxCandidates}</span>
            </div>
            <input
              type="range"
              min={10}
              max={100}
              step={5}
              value={maxCandidates}
              onChange={(e) => { setMaxCandidates(Number(e.target.value)); setDirty(true) }}
              className="w-full"
            />
            <div className="flex justify-between">
              <span className="text-[9px]" style={{ color: theme.colors.textHint }}>10 ({t.settings.fastest})</span>
              <span className="text-[9px]" style={{ color: theme.colors.textHint }}>100 ({t.settings.mostCoverage})</span>
            </div>
          </div>

          <p className="text-[10px]" style={{ color: theme.colors.textHint }}>
            {t.settings.preFilterDesc.replace('{max}', String(maxCandidates)).replace('{aiDesc}', aiEnabled ? t.settings.aiOnDesc.replace('{limit}', String(aiLimit)) : t.settings.aiOffDesc)}
          </p>
        </div>
      </Card>

      {/* Score Thresholds */}
      <Card>
        <div className="flex items-center justify-between mb-4">
          <p className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: theme.colors.textSub }}>
            {t.settings.signalThresholds}
          </p>
        </div>
        <div className="space-y-5">
          {/* Safe Income BUY threshold */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <p className="text-sm font-medium" style={{ color: theme.colors.text }}>{t.settings.safeIncomeBuy}</p>
              <span className="text-sm font-bold tabular-nums" style={{ color: theme.colors.up }}>{scoreBuySafe}+</span>
            </div>
            <input
              type="range" min={55} max={75} value={scoreBuySafe}
              onChange={(e) => { setScoreBuySafe(Number(e.target.value)); setDirty(true) }}
              className="w-full"
            />
            <div className="flex justify-between items-center mt-1">
              <span className="text-[9px]" style={{ color: theme.colors.textHint }}>55 ({t.settings.moreSignals})</span>
              <span className="text-[10px] font-semibold tabular-nums" style={{ color: theme.colors.up }}>
                {scoreBuySafe <= 60 ? '~61%' : scoreBuySafe <= 62 ? '~61%' : scoreBuySafe <= 65 ? '~59%' : scoreBuySafe <= 68 ? '~57%' : scoreBuySafe <= 70 ? '~59%' : '~62%'} {t.settings.winRate}
              </span>
              <span className="text-[9px]" style={{ color: theme.colors.textHint }}>75 ({t.settings.fewerStricter})</span>
            </div>
            <p className="text-[9px] mt-1" style={{ color: theme.colors.textHint }}>
              {t.settings.backtestValidated.replace('{threshold}', String(scoreBuySafe)).replace('{count}', scoreBuySafe <= 60 ? '6,033' : scoreBuySafe <= 62 ? '5,489' : scoreBuySafe <= 65 ? '3,631' : scoreBuySafe <= 68 ? '1,475' : scoreBuySafe <= 70 ? '564' : '102')}
            </p>
          </div>

          {/* High Risk BUY threshold */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <p className="text-sm font-medium" style={{ color: theme.colors.text }}>{t.settings.highRiskBuy}</p>
              <span className="text-sm font-bold tabular-nums" style={{ color: theme.colors.primary }}>{scoreBuyRisk}+</span>
            </div>
            <input
              type="range" min={55} max={75} value={scoreBuyRisk}
              onChange={(e) => { setScoreBuyRisk(Number(e.target.value)); setDirty(true) }}
              className="w-full"
            />
            <div className="flex justify-between items-center mt-1">
              <span className="text-[9px]" style={{ color: theme.colors.textHint }}>55 ({t.settings.moreSignals})</span>
              <span className="text-[10px] font-semibold tabular-nums" style={{ color: theme.colors.primary }}>
                {scoreBuyRisk <= 60 ? '~53%' : scoreBuyRisk <= 62 ? '~52%' : scoreBuyRisk <= 65 ? '~53%' : scoreBuyRisk <= 68 ? '~52%' : scoreBuyRisk <= 70 ? '~52%' : '~48%'} {t.settings.winRate}
              </span>
              <span className="text-[9px]" style={{ color: theme.colors.textHint }}>75 ({t.settings.fewerStricter})</span>
            </div>
            <p className="text-[9px] mt-1" style={{ color: theme.colors.textHint }}>
              {t.settings.highRiskNeedsAi}
            </p>
          </div>

          {/* HOLD threshold */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <p className="text-sm font-medium" style={{ color: theme.colors.text }}>{t.settings.holdAvoidCutoff}</p>
              <span className="text-sm font-bold tabular-nums" style={{ color: theme.colors.warning }}>{scoreHold}</span>
            </div>
            <input
              type="range" min={40} max={60} value={scoreHold}
              onChange={(e) => { setScoreHold(Number(e.target.value)); setDirty(true) }}
              className="w-full"
            />
            <div className="flex justify-between">
              <span className="text-[9px]" style={{ color: theme.colors.textHint }}>40 ({t.settings.lenient})</span>
              <span className="text-[9px]" style={{ color: theme.colors.textHint }}>60 ({t.settings.strict})</span>
            </div>
            <p className="text-[9px] mt-1" style={{ color: theme.colors.textHint }}>
              {t.settings.belowScoreAvoid}
            </p>
          </div>
        </div>
      </Card>

      {/* Watchdog */}
      <Card>
        <div className="flex items-center justify-between mb-4">
          <p className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: theme.colors.textSub }}>
            {t.settings.watchdog ?? 'Brain Watchdog'}
          </p>
        </div>
        <div className="space-y-5">
          {/* Min notification threshold */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <p className="text-sm font-medium" style={{ color: theme.colors.text }}>
                {t.settings.minNotifyThreshold ?? 'Min Alert Threshold'}
              </p>
              <span className="text-sm font-bold tabular-nums" style={{ color: theme.colors.warning }}>
                {wdMinNotify.toFixed(1)}%
              </span>
            </div>
            <input
              type="range" min={0} max={3} step={0.1} value={wdMinNotify}
              onChange={(e) => { setWdMinNotify(Number(e.target.value)); setDirty(true) }}
              className="w-full"
            />
            <div className="flex justify-between">
              <span className="text-[9px]" style={{ color: theme.colors.textHint }}>0% ({t.settings.allAlerts ?? 'All alerts'})</span>
              <span className="text-[9px]" style={{ color: theme.colors.textHint }}>3% ({t.settings.significantOnly ?? 'Significant only'})</span>
            </div>
            <p className="text-[9px] mt-1" style={{ color: theme.colors.textHint }}>
              {t.settings.minNotifyDesc ?? 'Moves smaller than this are logged but won\'t send Telegram notifications.'}
            </p>
          </div>

          {/* P&L alert threshold */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <p className="text-sm font-medium" style={{ color: theme.colors.text }}>
                {t.settings.pnlAlertThreshold ?? 'Interval Drop Alert'}
              </p>
              <span className="text-sm font-bold tabular-nums" style={{ color: theme.colors.down }}>
                -{wdPnlAlert.toFixed(1)}%
              </span>
            </div>
            <input
              type="range" min={0.5} max={5} step={0.5} value={wdPnlAlert}
              onChange={(e) => { setWdPnlAlert(Number(e.target.value)); setDirty(true) }}
              className="w-full"
            />
            <div className="flex justify-between">
              <span className="text-[9px]" style={{ color: theme.colors.textHint }}>0.5% ({t.settings.sensitive ?? 'Sensitive'})</span>
              <span className="text-[9px]" style={{ color: theme.colors.textHint }}>5% ({t.settings.relaxed ?? 'Relaxed'})</span>
            </div>
            <p className="text-[9px] mt-1" style={{ color: theme.colors.textHint }}>
              {t.settings.pnlAlertDesc ?? 'Triggers concern when a position drops this much in a single 15-min interval.'}
            </p>
          </div>

          {/* Max brain positions */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <p className="text-sm font-medium" style={{ color: theme.colors.text }}>
                {t.settings.maxBrainPositions ?? 'Max Brain Positions'}
              </p>
              <span className="text-sm font-bold tabular-nums" style={{ color: theme.colors.primary }}>
                {brainMaxOpen}
              </span>
            </div>
            <input
              type="range" min={5} max={50} step={1} value={brainMaxOpen}
              onChange={(e) => { setBrainMaxOpen(Number(e.target.value)); setDirty(true) }}
              className="w-full"
            />
            <div className="flex justify-between">
              <span className="text-[9px]" style={{ color: theme.colors.textHint }}>5 ({t.settings.conservative ?? 'Conservative'})</span>
              <span className="text-[9px]" style={{ color: theme.colors.textHint }}>50 ({t.settings.aggressive ?? 'Aggressive'})</span>
            </div>
            <p className="text-[9px] mt-1" style={{ color: theme.colors.textHint }}>
              {t.settings.maxBrainDesc ?? 'Maximum concurrent brain auto-picks. When full, the brain rotates out weaker positions for stronger signals.'}
            </p>
          </div>

          {/* Quiet Hours */}
          <div>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium" style={{ color: theme.colors.text }}>
                  {t.settings.quietHours ?? 'Quiet Hours'}
                </p>
                <p className="text-[10px]" style={{ color: theme.colors.textSub }}>
                  {t.settings.quietHoursDesc ?? 'Block Telegram notifications during these hours.'}
                </p>
              </div>
              <button
                onClick={() => { setQuietEnabled(!quietEnabled); setDirty(true) }}
                className="w-11 h-6 rounded-full transition-all relative"
                style={{ backgroundColor: quietEnabled ? theme.colors.primary : theme.colors.border }}
              >
                <div
                  className="w-5 h-5 rounded-full bg-white absolute top-0.5 transition-all"
                  style={{ left: quietEnabled ? 22 : 2 }}
                />
              </button>
            </div>
            {quietEnabled && (
              <div
                className="mt-2 flex items-center gap-3 rounded-lg px-3 py-2"
                style={{ backgroundColor: theme.colors.surfaceAlt, border: `1px solid ${theme.colors.border}` }}
              >
                <span className="text-[11px] font-medium" style={{ color: theme.colors.textSub }}>
                  {(t.settings.quietHoursRange ?? '{start} PM - {end} AM ET')
                    .replace('{start}', String(quietStart > 12 ? quietStart - 12 : quietStart))
                    .replace('{end}', String(quietEnd > 12 ? quietEnd - 12 : quietEnd))}
                </span>
              </div>
            )}
          </div>
        </div>
      </Card>

      {/* Theme */}
      <Card>
        <p className="text-[11px] font-semibold uppercase tracking-wide mb-4" style={{ color: theme.colors.textSub }}>
          {t.settings.themeLabel}
        </p>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          {themeIds.map((id) => {
            const th = themes[id]
            const isActive = theme.id === id
            return (
              <button
                key={id}
                onClick={() => setTheme(id)}
                className="relative text-left rounded-xl p-3 transition-all hover:scale-[1.02]"
                style={{
                  backgroundColor: th.colors.bg,
                  border: isActive ? `2px solid ${th.colors.primary}` : `1px solid ${theme.colors.border}`,
                }}
              >
                {isActive && (
                  <div
                    className="absolute top-2 right-2 w-5 h-5 rounded-full flex items-center justify-center"
                    style={{ backgroundColor: th.colors.primary }}
                  >
                    <Check size={12} style={{ color: '#fff' }} />
                  </div>
                )}
                <p className="text-sm font-semibold mb-1" style={{ color: th.colors.text }}>
                  {th.name}
                </p>
                <div className="flex gap-1.5 mt-2">
                  {[th.colors.primary, th.colors.up, th.colors.down, th.colors.warning].map((c) => (
                    <span key={c} className="w-4 h-4 rounded-full" style={{ backgroundColor: c }} />
                  ))}
                </div>
              </button>
            )
          })}
        </div>
      </Card>

      {/* Language */}
      <Card>
        <p className="text-[11px] font-semibold uppercase tracking-wide mb-4" style={{ color: theme.colors.textSub }}>
          {t.settings.languageLabel}
        </p>
        <div className="flex gap-3">
          {([['en', 'English', '🇨🇦'], ['pt', 'Portugues', '🇧🇷']] as const).map(([code, label, flag]) => {
            const isActive = locale === code
            return (
              <button
                key={code}
                onClick={() => setLocale(code)}
                className="flex items-center gap-2 rounded-xl px-4 py-3 transition-all flex-1"
                style={{
                  backgroundColor: isActive ? theme.colors.primary + '12' : theme.colors.surfaceAlt,
                  border: isActive ? `2px solid ${theme.colors.primary}` : `1px solid ${theme.colors.border}`,
                  color: isActive ? theme.colors.primary : theme.colors.text,
                }}
              >
                <span className="text-lg">{flag}</span>
                <span className="text-sm font-medium">{label}</span>
                {isActive && <Check size={16} className="ml-auto" />}
              </button>
            )
          })}
        </div>
      </Card>

      {/* Account */}
      <Card>
        <p className="text-[11px] font-semibold uppercase tracking-wide mb-4" style={{ color: theme.colors.textSub }}>
          {t.settings.account}
        </p>
        <Button variant="secondary" onClick={handleLogout}>
          {t.settings.logOut}
        </Button>
      </Card>
    </div>
  )
}
