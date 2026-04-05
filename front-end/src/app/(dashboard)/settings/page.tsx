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
}: {
  label: string
  providers: string[]
  available: Record<string, { configured: boolean; model: string }>
  onReorder: (newOrder: string[]) => void
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
                <p className="text-sm font-medium" style={{ color: theme.colors.text }}>
                  {meta.name}
                </p>
                <p className="text-[10px]" style={{ color: theme.colors.textSub }}>
                  {info?.model || t.settings.notConfigured} {configured ? '' : t.settings.noApiKey}
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
  const [dirty, setDirty] = useState(false)

  useEffect(() => {
    if (aiConfig) {
      setSynthProviders(aiConfig.synthesis.providers)
      setSentProviders(aiConfig.sentiment.providers)
      if (aiConfig.scanning) {
        setAiEnabled(aiConfig.scanning.ai_enabled)
        setAiLimit(aiConfig.scanning.ai_candidate_limit)
        setMaxCandidates(aiConfig.scanning.max_candidates)
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
      })
      toast.show(t.settings.configSaved, 'success')
      setDirty(false)
    } catch {
      toast.show(t.settings.configSaveFailed, 'error')
    }
  }, [synthProviders, sentProviders, aiEnabled, aiLimit, maxCandidates, toast, t])

  const handleLogout = () => {
    logout()
    router.push('/login')
  }

  return (
    <div className="space-y-6 max-w-[600px]">
      <h1 className="text-2xl font-bold" style={{ color: theme.colors.text }}>
        {t.settings.title}
      </h1>

      {/* AI Providers */}
      <Card>
        <div className="flex items-center justify-between mb-4">
          <p className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: theme.colors.textSub }}>
            {t.settings.aiProviders}
          </p>
          {dirty && (
            <Button onClick={handleSave}>{t.settings.save}</Button>
          )}
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
          {dirty && <Button onClick={handleSave}>{t.settings.save}</Button>}
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
                  {[th.colors.primary, th.colors.up, th.colors.down, th.colors.warning].map((c, i) => (
                    <span key={i} className="w-4 h-4 rounded-full" style={{ backgroundColor: c }} />
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
