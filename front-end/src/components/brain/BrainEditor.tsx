'use client'

import { useState, useEffect, useMemo } from 'react'
import { useTheme } from '@/hooks/useTheme'
import { useToast } from '@/hooks/useToast'
import { useBrainStore } from '@/store/brainStore'
import { useBrainRules, useBrainKnowledge, useBrainAudit, useBrainSuggestions, useUpdateRule, useUpdateKnowledge } from '@/hooks/useBrain'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Brain, Lock, Clock } from 'lucide-react'
import { useI18nStore } from '@/store/i18nStore'
import { BrainWorkflow } from './BrainWorkflow'
import { BrainRulesTab } from './BrainRulesTab'
import { BrainKnowledgeTab } from './BrainKnowledgeTab'
import { BrainAuditTab } from './BrainAuditTab'
import { BrainSuggestionsTab } from './BrainSuggestionsTab'

type Tab = 'rules' | 'knowledge' | 'audit' | 'workflow' | 'suggestions'

function Timer() {
  const theme = useTheme()
  const remaining = useBrainStore((s) => s.getRemainingSeconds)
  const [secs, setSecs] = useState(remaining())

  useEffect(() => {
    const t = setInterval(() => setSecs(remaining()), 1000)
    return () => clearInterval(t)
  }, [remaining])

  const mins = Math.floor(secs / 60)
  const s = secs % 60
  const color = secs > 180 ? theme.colors.up : secs > 60 ? theme.colors.warning : theme.colors.down

  return (
    <span className="text-sm font-semibold tabular-nums flex items-center gap-1.5" style={{ color }}>
      <Clock size={14} />
      {mins}:{s.toString().padStart(2, '0')}
    </span>
  )
}

export function BrainEditor() {
  const theme = useTheme()
  const toast = useToast()
  const t = useI18nStore((s) => s.t)
  const lock = useBrainStore((s) => s.lock)
  const { data: rules, isLoading: rulesLoading } = useBrainRules()
  const { data: knowledge, isLoading: knowledgeLoading } = useBrainKnowledge()
  const { data: auditLog } = useBrainAudit()
  const { data: suggestions } = useBrainSuggestions()
  const updateRule = useUpdateRule()
  const updateKnowledge = useUpdateKnowledge()

  const [tab, setTab] = useState<Tab>('rules')
  const [ruleFilter, setRuleFilter] = useState<string>('ALL')

  const rulesList = useMemo(() => (rules ?? []) as Record<string, unknown>[], [rules])
  const knowledgeList = useMemo(() => (knowledge ?? []) as Record<string, unknown>[], [knowledge])
  const auditList = useMemo(() => (auditLog ?? []) as Record<string, unknown>[], [auditLog])
  const suggestionsList = useMemo(() => (suggestions ?? []) as Record<string, unknown>[], [suggestions])
  const pendingSuggestions = useMemo(() => suggestionsList.filter((s) => s.status === 'PENDING'), [suggestionsList])

  const handleRuleSave = async (ruleId: string, data: Record<string, unknown>) => {
    try {
      await updateRule.mutateAsync({ id: ruleId, data })
      toast.show(t.brain.ruleSaved, 'success')
    } catch (err) {
      toast.show((err as Error)?.message || t.brain.failedToSave, 'error')
    }
  }

  const handleKnowledgeSave = async (knowledgeId: string, data: Record<string, unknown>) => {
    try {
      await updateKnowledge.mutateAsync({ id: knowledgeId, data })
      toast.show(t.brain.knowledgeSaved, 'success')
    } catch (err) {
      toast.show((err as Error)?.message || t.brain.failedToSave, 'error')
    }
  }

  const tabs: { label: string; value: Tab }[] = [
    { label: t.brain.pipeline, value: 'workflow' },
    { label: `${t.brain.rules} (${rulesList.length})`, value: 'rules' },
    { label: `${t.brain.knowledge} (${knowledgeList.length})`, value: 'knowledge' },
    { label: `${t.brain.suggestions}${pendingSuggestions.length > 0 ? ` (${pendingSuggestions.length})` : ''}`, value: 'suggestions' },
    { label: t.brain.auditLog, value: 'audit' },
  ]

  return (
    <div className="space-y-4">
      {/* Header */}
      <div
        className="flex items-center justify-between rounded-xl px-4 py-3"
        style={{ backgroundColor: theme.colors.primary + '08', border: `1px solid ${theme.colors.primary}20` }}
      >
        <div className="flex items-center gap-3">
          <Brain size={20} style={{ color: theme.colors.primary }} />
          <span className="text-sm font-bold" style={{ color: theme.colors.text }}>{t.brain.editor}</span>
          <Badge variant="confirmed">{t.brain.unlocked}</Badge>
        </div>
        <div className="flex items-center gap-3">
          <Timer />
          <Button variant="secondary" onClick={lock}>
            <span className="flex items-center gap-1.5"><Lock size={12} /> {t.brain.lock}</span>
          </Button>
        </div>
      </div>

      {/* Tabs */}
      <div role="tablist" className="flex items-center gap-0.5 rounded-lg px-0.5 py-0.5 overflow-x-auto" style={{ backgroundColor: theme.colors.nav }}>
        {tabs.map((t) => (
          <button
            key={t.value}
            role="tab"
            id={`tab-${t.value}`}
            aria-selected={tab === t.value}
            aria-controls={`tabpanel-${t.value}`}
            onClick={() => setTab(t.value)}
            className="px-3 py-1.5 rounded-md text-xs font-medium transition-all"
            style={{
              backgroundColor: tab === t.value ? theme.colors.navActive : 'transparent',
              color: tab === t.value ? theme.colors.text : theme.colors.textSub,
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab panels */}
      {tab === 'workflow' && (
        <div role="tabpanel" id="tabpanel-workflow" aria-labelledby="tab-workflow">
          <BrainWorkflow
            unlocked
            onViewRules={(ruleType) => {
              setRuleFilter(ruleType)
              setTab('rules')
            }}
          />
        </div>
      )}

      {tab === 'rules' && (
        <BrainRulesTab
          rules={rulesList}
          isLoading={rulesLoading}
          ruleFilter={ruleFilter}
          onRuleFilterChange={setRuleFilter}
          onRuleSave={handleRuleSave}
        />
      )}

      {tab === 'knowledge' && (
        <BrainKnowledgeTab
          knowledge={knowledgeList}
          isLoading={knowledgeLoading}
          onKnowledgeSave={handleKnowledgeSave}
        />
      )}

      {tab === 'suggestions' && (
        <BrainSuggestionsTab suggestions={suggestionsList} />
      )}

      {tab === 'audit' && (
        <BrainAuditTab auditLog={auditList} />
      )}
    </div>
  )
}
