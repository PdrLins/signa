'use client'

import { useState, useEffect } from 'react'
import { useTheme } from '@/hooks/useTheme'
import { useToast } from '@/hooks/useToast'
import { useBrainStore } from '@/store/brainStore'
import { useBrainRules, useBrainKnowledge, useBrainAudit, useBrainSuggestions, useRunAnalysis, useApproveSuggestion, useRejectSuggestion, useApplySuggestion, useUpdateRule, useUpdateKnowledge } from '@/hooks/useBrain'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Skeleton } from '@/components/ui/Skeleton'
import { Brain, Lock, Clock } from 'lucide-react'
import { useI18nStore } from '@/store/i18nStore'
import { BrainWorkflow } from './BrainWorkflow'

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

function RuleCard({ rule, onEdit }: { rule: Record<string, unknown>; onEdit: () => void }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const isActive = rule.is_active as boolean
  return (
    <div
      className="rounded-xl px-4 py-3 space-y-2"
      style={{
        backgroundColor: theme.colors.surfaceAlt,
        border: `1px solid ${theme.colors.border}`,
        opacity: isActive ? 1 : 0.5,
      }}
    >
      <div className="flex items-center justify-between">
        <span className="text-sm font-semibold" style={{ color: theme.colors.text }}>
          {rule.name as string}
        </span>
        <Badge variant={isActive ? 'confirmed' : 'cancelled'}>{isActive ? t.brain.active : t.brain.inactive}</Badge>
      </div>
      <div className="flex items-center gap-1.5 flex-wrap">
        <Badge variant="hold">{rule.rule_type as string}</Badge>
        <Badge variant={rule.bucket === 'HIGH_RISK' ? 'risk' : rule.bucket === 'SAFE_INCOME' ? 'safe' : 'hold'}>
          {rule.bucket as string}
        </Badge>
        {Boolean(rule.is_blocker) && <Badge variant="sell">{t.brain.blocker}</Badge>}
      </div>
      <p className="text-xs leading-relaxed" style={{ color: theme.colors.textSub }}>
        {rule.description as string}
      </p>
      {Boolean(rule.formula) && (
        <p className="text-[11px] font-mono" style={{ color: theme.colors.textHint }}>
          {String(rule.formula)}
        </p>
      )}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {Number(rule.weight_safe) > 0 && <span className="text-[10px]" style={{ color: theme.colors.up }}>Safe: {String(rule.weight_safe)}</span>}
          {Number(rule.weight_risk) > 0 && <span className="text-[10px]" style={{ color: theme.colors.primary }}>Risk: {String(rule.weight_risk)}</span>}
          {Boolean(rule.source_name) && <span className="text-[10px]" style={{ color: theme.colors.textHint }}>{String(rule.source_name)}</span>}
        </div>
        <Button variant="secondary" onClick={onEdit}>{t.brain.edit}</Button>
      </div>
    </div>
  )
}

function RuleEditForm({ rule, onSave, onCancel }: {
  rule: Record<string, unknown>
  onSave: (data: Record<string, unknown>) => void
  onCancel: () => void
}) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const [form, setForm] = useState({
    description: (rule.description as string) || '',
    formula: (rule.formula as string) || '',
    threshold_min: rule.threshold_min as number | null,
    threshold_max: rule.threshold_max as number | null,
    threshold_unit: (rule.threshold_unit as string) || 'absolute',
    weight_safe: (rule.weight_safe as number) || 0,
    weight_risk: (rule.weight_risk as number) || 0,
    is_blocker: (rule.is_blocker as boolean) || false,
    is_active: (rule.is_active as boolean) ?? true,
    notes: (rule.notes as string) || '',
  })
  const [confirming, setConfirming] = useState(false)

  const handleSave = () => {
    if (!confirming) { setConfirming(true); return }
    onSave(form)
    setConfirming(false)
  }

  return (
    <div
      className="rounded-xl px-4 py-4 space-y-3 mt-2"
      style={{ backgroundColor: theme.colors.surface, border: `2px solid ${theme.colors.primary}30` }}
    >
      <p className="text-sm font-semibold" style={{ color: theme.colors.primary }}>
        {t.brain.editing} {rule.name as string}
      </p>

      <label className="block">
        <span className="text-[10px] uppercase tracking-wide" style={{ color: theme.colors.textHint }}>{t.brain.description}</span>
        <textarea
          rows={3}
          value={form.description}
          onChange={(e) => setForm({ ...form, description: e.target.value })}
          className="w-full mt-1 px-3 py-2 rounded-lg text-sm outline-none resize-y"
          style={{ backgroundColor: theme.colors.surfaceAlt, border: `1px solid ${theme.colors.border}`, color: theme.colors.text }}
        />
      </label>

      <label className="block">
        <span className="text-[10px] uppercase tracking-wide" style={{ color: theme.colors.textHint }}>{t.brain.formula}</span>
        <input
          value={form.formula}
          onChange={(e) => setForm({ ...form, formula: e.target.value })}
          className="w-full mt-1 px-3 py-2 rounded-lg text-sm outline-none"
          style={{ backgroundColor: theme.colors.surfaceAlt, border: `1px solid ${theme.colors.border}`, color: theme.colors.text }}
        />
      </label>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <label>
          <span className="text-[10px] uppercase tracking-wide" style={{ color: theme.colors.textHint }}>{t.brain.min}</span>
          <input type="number" step="any" value={form.threshold_min ?? ''} onChange={(e) => setForm({ ...form, threshold_min: e.target.value ? Number(e.target.value) : null })}
            className="w-full mt-1 px-2 py-1.5 rounded-lg text-sm outline-none" style={{ backgroundColor: theme.colors.surfaceAlt, border: `1px solid ${theme.colors.border}`, color: theme.colors.text }} />
        </label>
        <label>
          <span className="text-[10px] uppercase tracking-wide" style={{ color: theme.colors.textHint }}>{t.brain.max}</span>
          <input type="number" step="any" value={form.threshold_max ?? ''} onChange={(e) => setForm({ ...form, threshold_max: e.target.value ? Number(e.target.value) : null })}
            className="w-full mt-1 px-2 py-1.5 rounded-lg text-sm outline-none" style={{ backgroundColor: theme.colors.surfaceAlt, border: `1px solid ${theme.colors.border}`, color: theme.colors.text }} />
        </label>
        <label>
          <span className="text-[10px] uppercase tracking-wide" style={{ color: theme.colors.textHint }}>{t.brain.unit}</span>
          <select value={form.threshold_unit} onChange={(e) => setForm({ ...form, threshold_unit: e.target.value })}
            className="w-full mt-1 px-2 py-1.5 rounded-lg text-sm outline-none" style={{ backgroundColor: theme.colors.surfaceAlt, border: `1px solid ${theme.colors.border}`, color: theme.colors.text }}>
            <option value="absolute">absolute</option>
            <option value="percent">percent</option>
            <option value="ratio">ratio</option>
            <option value="z-score">z-score</option>
            <option value="days">days</option>
            <option value="category">category</option>
            <option value="event">event</option>
          </select>
        </label>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <label>
          <span className="text-[10px] uppercase tracking-wide" style={{ color: theme.colors.textHint }}>{t.brain.weightSafe}</span>
          <input type="number" step="0.01" min="0" max="1" value={form.weight_safe} onChange={(e) => setForm({ ...form, weight_safe: Number(e.target.value) })}
            className="w-full mt-1 px-2 py-1.5 rounded-lg text-sm outline-none" style={{ backgroundColor: theme.colors.surfaceAlt, border: `1px solid ${theme.colors.border}`, color: theme.colors.text }} />
        </label>
        <label>
          <span className="text-[10px] uppercase tracking-wide" style={{ color: theme.colors.textHint }}>{t.brain.weightRisk}</span>
          <input type="number" step="0.01" min="0" max="1" value={form.weight_risk} onChange={(e) => setForm({ ...form, weight_risk: Number(e.target.value) })}
            className="w-full mt-1 px-2 py-1.5 rounded-lg text-sm outline-none" style={{ backgroundColor: theme.colors.surfaceAlt, border: `1px solid ${theme.colors.border}`, color: theme.colors.text }} />
        </label>
      </div>

      <div className="flex items-center gap-4">
        <label className="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={form.is_blocker} onChange={(e) => setForm({ ...form, is_blocker: e.target.checked })} />
          <span className="text-xs" style={{ color: theme.colors.text }}>{t.brain.isBlocker}</span>
        </label>
        <label className="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
          <span className="text-xs" style={{ color: theme.colors.text }}>{t.brain.activeLabel}</span>
        </label>
      </div>

      <label className="block">
        <span className="text-[10px] uppercase tracking-wide" style={{ color: theme.colors.textHint }}>{t.brain.notes}</span>
        <textarea rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })}
          className="w-full mt-1 px-3 py-2 rounded-lg text-sm outline-none resize-y"
          style={{ backgroundColor: theme.colors.surfaceAlt, border: `1px solid ${theme.colors.border}`, color: theme.colors.text }} />
      </label>

      <p className="text-[10px]" style={{ color: theme.colors.textHint }}>
        {t.brain.readonlyNote}
      </p>

      <div className="flex gap-2 pt-1">
        <Button variant="secondary" onClick={onCancel} fullWidth>{t.brain.cancel}</Button>
        <Button onClick={handleSave} fullWidth>
          {confirming ? t.brain.confirmSave : t.brain.saveChanges}
        </Button>
      </div>
    </div>
  )
}

function KnowledgeCard({ entry, onEdit }: { entry: Record<string, unknown>; onEdit: () => void }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const [expanded, setExpanded] = useState(false)
  const isActive = entry.is_active as boolean
  const explanation = (entry.explanation as string) || ''

  return (
    <div
      className="rounded-xl px-4 py-3 space-y-2"
      style={{ backgroundColor: theme.colors.surfaceAlt, border: `1px solid ${theme.colors.border}`, opacity: isActive ? 1 : 0.5 }}
    >
      <div className="flex items-center justify-between">
        <span className="text-sm font-semibold" style={{ color: theme.colors.text }}>{entry.key_concept as string}</span>
        <Badge variant={isActive ? 'confirmed' : 'cancelled'}>{isActive ? t.brain.active : t.brain.inactive}</Badge>
      </div>
      <Badge variant="hold">{entry.topic as string}</Badge>
      <p className="text-xs leading-relaxed" style={{ color: theme.colors.textSub }}>
        {expanded ? explanation : explanation.slice(0, 150) + (explanation.length > 150 ? '...' : '')}
      </p>
      {explanation.length > 150 && (
        <button onClick={() => setExpanded(!expanded)} className="text-[10px] font-medium" style={{ color: theme.colors.primary }}>
          {expanded ? t.brain.showLess : t.brain.readMore}
        </button>
      )}
      <div className="flex items-center justify-between">
        <span className="text-[10px]" style={{ color: theme.colors.textHint }}>{entry.source_name as string}</span>
        <Button variant="secondary" onClick={onEdit}>{t.brain.edit}</Button>
      </div>
    </div>
  )
}

function KnowledgeEditForm({ entry, onSave, onCancel }: {
  entry: Record<string, unknown>
  onSave: (data: Record<string, unknown>) => void
  onCancel: () => void
}) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const [form, setForm] = useState({
    explanation: (entry.explanation as string) || '',
    formula: (entry.formula as string) || '',
    example: (entry.example as string) || '',
    is_active: (entry.is_active as boolean) ?? true,
    notes: (entry.notes as string) || '',
  })
  const [confirming, setConfirming] = useState(false)

  const handleSave = () => {
    if (!confirming) { setConfirming(true); return }
    onSave(form)
    setConfirming(false)
  }

  return (
    <div className="rounded-xl px-4 py-4 space-y-3 mt-2" style={{ backgroundColor: theme.colors.surface, border: `2px solid ${theme.colors.primary}30` }}>
      <p className="text-sm font-semibold" style={{ color: theme.colors.primary }}>{t.brain.editing} {entry.key_concept as string}</p>
      <label className="block">
        <span className="text-[10px] uppercase tracking-wide" style={{ color: theme.colors.textHint }}>{t.brain.explanation}</span>
        <textarea rows={6} value={form.explanation} onChange={(e) => setForm({ ...form, explanation: e.target.value })}
          className="w-full mt-1 px-3 py-2 rounded-lg text-sm outline-none resize-y"
          style={{ backgroundColor: theme.colors.surfaceAlt, border: `1px solid ${theme.colors.border}`, color: theme.colors.text }} />
      </label>
      <label className="block">
        <span className="text-[10px] uppercase tracking-wide" style={{ color: theme.colors.textHint }}>{t.brain.formulaOptional}</span>
        <input value={form.formula} onChange={(e) => setForm({ ...form, formula: e.target.value })}
          className="w-full mt-1 px-3 py-2 rounded-lg text-sm outline-none"
          style={{ backgroundColor: theme.colors.surfaceAlt, border: `1px solid ${theme.colors.border}`, color: theme.colors.text }} />
      </label>
      <label className="block">
        <span className="text-[10px] uppercase tracking-wide" style={{ color: theme.colors.textHint }}>{t.brain.exampleOptional}</span>
        <textarea rows={2} value={form.example} onChange={(e) => setForm({ ...form, example: e.target.value })}
          className="w-full mt-1 px-3 py-2 rounded-lg text-sm outline-none resize-y"
          style={{ backgroundColor: theme.colors.surfaceAlt, border: `1px solid ${theme.colors.border}`, color: theme.colors.text }} />
      </label>
      <label className="block">
        <span className="text-[10px] uppercase tracking-wide" style={{ color: theme.colors.textHint }}>{t.brain.notes}</span>
        <textarea rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })}
          className="w-full mt-1 px-3 py-2 rounded-lg text-sm outline-none resize-y"
          style={{ backgroundColor: theme.colors.surfaceAlt, border: `1px solid ${theme.colors.border}`, color: theme.colors.text }} />
      </label>
      <label className="flex items-center gap-2 cursor-pointer">
        <input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
        <span className="text-xs" style={{ color: theme.colors.text }}>{t.brain.activeLabel}</span>
      </label>
      <p className="text-[10px]" style={{ color: theme.colors.textHint }}>{t.brain.knowledgeReadonlyNote}</p>
      <div className="flex gap-2 pt-1">
        <Button variant="secondary" onClick={onCancel} fullWidth>{t.brain.cancel}</Button>
        <Button onClick={handleSave} fullWidth>{confirming ? t.brain.confirmSave : t.brain.saveChanges}</Button>
      </div>
    </div>
  )
}

function AuditEntry({ event }: { event: Record<string, unknown> }) {
  const theme = useTheme()
  const type = event.event_type as string
  const color = type.includes('GRANTED') ? theme.colors.up
    : type.includes('DENIED') || type.includes('LOCKED') ? theme.colors.down
    : theme.colors.primary

  const meta = (event.metadata ?? {}) as Record<string, unknown>
  const created = event.created_at ? new Date(event.created_at as string).toLocaleString() : ''

  return (
    <div className="rounded-xl px-4 py-3 space-y-1" style={{ backgroundColor: theme.colors.surfaceAlt, border: `1px solid ${theme.colors.border}` }}>
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold" style={{ color }}>{type}</span>
        <span className="text-[10px]" style={{ color: theme.colors.textHint }}>{created}</span>
      </div>
      {Boolean(meta.rule_name) && <p className="text-xs" style={{ color: theme.colors.text }}>{String(meta.rule_name)}</p>}
      {Boolean(meta.key_concept) && <p className="text-xs" style={{ color: theme.colors.text }}>{String(meta.key_concept)}</p>}
      {Array.isArray(meta.changed_fields) && (
        <p className="text-[10px]" style={{ color: theme.colors.textSub }}>Changed: {(meta.changed_fields as string[]).join(', ')}</p>
      )}
      {(() => {
        const before = meta.before as Record<string, unknown> | undefined
        const after = meta.after as Record<string, unknown> | undefined
        if (!before || !after || typeof before !== 'object') return null
        return (
          <div className="text-[10px] font-mono" style={{ color: theme.colors.textHint }}>
            {Object.keys(before).map((k) => (
              <p key={k}>{k}: {String(before[k])} → {String(after[k])}</p>
            ))}
          </div>
        )
      })()}
      <p className="text-[10px]" style={{ color: theme.colors.textHint }}>IP: {event.ip_address as string}</p>
    </div>
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
  const runAnalysis = useRunAnalysis()
  const approveSuggestion = useApproveSuggestion()
  const rejectSuggestion = useRejectSuggestion()
  const applySuggestion = useApplySuggestion()
  const updateRule = useUpdateRule()
  const updateKnowledge = useUpdateKnowledge()

  const [tab, setTab] = useState<Tab>('rules')
  const [editingRule, setEditingRule] = useState<string | null>(null)
  const [editingKnowledge, setEditingKnowledge] = useState<string | null>(null)
  const [ruleFilter, setRuleFilter] = useState<string>('ALL')

  const rulesList = (rules ?? []) as Record<string, unknown>[]
  const filteredRules = ruleFilter === 'ALL' ? rulesList : rulesList.filter((r) => r.rule_type === ruleFilter)
  const ruleTypes = ['ALL', ...Array.from(new Set(rulesList.map((r) => r.rule_type as string)))]
  const knowledgeList = (knowledge ?? []) as Record<string, unknown>[]
  const auditList = (auditLog ?? []) as Record<string, unknown>[]
  const suggestionsList = (suggestions ?? []) as Record<string, unknown>[]
  const pendingSuggestions = suggestionsList.filter((s) => s.status === 'PENDING')

  const handleRuleSave = async (ruleId: string, data: Record<string, unknown>) => {
    try {
      await updateRule.mutateAsync({ id: ruleId, data })
      toast.show(t.brain.ruleSaved, 'success')
      setEditingRule(null)
    } catch (err) {
      toast.show((err as Error)?.message || t.brain.failedToSave, 'error')
    }
  }

  const handleKnowledgeSave = async (knowledgeId: string, data: Record<string, unknown>) => {
    try {
      await updateKnowledge.mutateAsync({ id: knowledgeId, data })
      toast.show(t.brain.knowledgeSaved, 'success')
      setEditingKnowledge(null)
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
      <div className="flex items-center gap-0.5 rounded-lg px-0.5 py-0.5 overflow-x-auto" style={{ backgroundColor: theme.colors.nav }}>
        {tabs.map((t) => (
          <button
            key={t.value}
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

      {/* Workflow tab */}
      {tab === 'workflow' && <BrainWorkflow />}

      {/* Rules tab */}
      {tab === 'rules' && (
        <div className="space-y-3">
          {/* Type filter */}
          <div className="flex flex-wrap gap-1.5">
            {ruleTypes.map((type) => (
              <button
                key={type}
                onClick={() => setRuleFilter(type)}
                className="px-2 py-1 rounded-lg text-[10px] font-medium"
                style={{
                  backgroundColor: ruleFilter === type ? theme.colors.primary + '15' : theme.colors.surfaceAlt,
                  color: ruleFilter === type ? theme.colors.primary : theme.colors.textSub,
                }}
              >
                {type} ({type === 'ALL' ? rulesList.length : rulesList.filter((r) => r.rule_type === type).length})
              </button>
            ))}
          </div>

          {rulesLoading ? (
            <Skeleton width="100%" height={200} />
          ) : (
            filteredRules.map((rule) => (
              <div key={rule.id as string}>
                <RuleCard rule={rule} onEdit={() => setEditingRule(editingRule === rule.id ? null : rule.id as string)} />
                {editingRule === rule.id && (
                  <RuleEditForm
                    rule={rule}
                    onSave={(data) => handleRuleSave(rule.id as string, data)}
                    onCancel={() => setEditingRule(null)}
                  />
                )}
              </div>
            ))
          )}
        </div>
      )}

      {/* Knowledge tab */}
      {tab === 'knowledge' && (
        <div className="space-y-3">
          {knowledgeLoading ? (
            <Skeleton width="100%" height={200} />
          ) : (
            knowledgeList.map((entry) => (
              <div key={entry.id as string}>
                <KnowledgeCard entry={entry} onEdit={() => setEditingKnowledge(editingKnowledge === entry.id ? null : entry.id as string)} />
                {editingKnowledge === entry.id && (
                  <KnowledgeEditForm
                    entry={entry}
                    onSave={(data) => handleKnowledgeSave(entry.id as string, data)}
                    onCancel={() => setEditingKnowledge(null)}
                  />
                )}
              </div>
            ))
          )}
        </div>
      )}

      {/* Suggestions tab */}
      {tab === 'suggestions' && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-xs" style={{ color: theme.colors.textSub }}>
              {t.brain.suggestionsDesc}
            </p>
            <Button
              onClick={() => {
                runAnalysis.mutate(7, {
                  onSuccess: (data) => toast.show(`${data.count} ${t.brain.suggestionsGenerated}`, 'success'),
                  onError: (err) => toast.show((err as Error)?.message || t.brain.analysisFailed, 'error'),
                })
              }}
              disabled={runAnalysis.isPending}
            >
              {runAnalysis.isPending ? t.brain.analyzing : t.brain.runAnalysis}
            </Button>
          </div>

          {suggestionsList.length === 0 ? (
            <p className="text-sm text-center py-8" style={{ color: theme.colors.textSub }}>
              {t.brain.noSuggestions}
            </p>
          ) : (
            suggestionsList.map((s) => {
              const isPending = s.status === 'PENDING'
              const isApproved = s.status === 'APPROVED'
              return (
                <div
                  key={String(s.id)}
                  className="rounded-xl px-4 py-3 space-y-2"
                  style={{ backgroundColor: theme.colors.surfaceAlt, border: `1px solid ${theme.colors.border}` }}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold" style={{ color: theme.colors.text }}>
                        {String(s.rule_name)}
                      </span>
                      <Badge variant={isPending ? 'hold' : isApproved ? 'confirmed' : s.status === 'APPLIED' ? 'buy' : 'cancelled'}>
                        {String(s.status)}
                      </Badge>
                    </div>
                    <span className="text-[10px]" style={{ color: theme.colors.textHint }}>
                      {String(s.suggestion_type)}
                    </span>
                  </div>

                  <p className="text-xs leading-relaxed" style={{ color: theme.colors.textSub }}>
                    {String(s.reasoning)}
                  </p>

                  {Boolean(s.expected_impact) && (
                    <p className="text-[10px]" style={{ color: theme.colors.primary }}>
                      Expected: {String(s.expected_impact)}
                    </p>
                  )}

                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="text-[10px]" style={{ color: theme.colors.textHint }}>
                        {t.brain.confidence}: {String(s.confidence)}%
                      </span>
                      <span className="text-[10px]" style={{ color: theme.colors.textHint }}>
                        {t.brain.winRate}: {s.win_rate ? `${(Number(s.win_rate) * 100).toFixed(0)}%` : '?'}
                      </span>
                    </div>
                    {isPending && (
                      <div className="flex items-center gap-1.5">
                        <button
                          onClick={() => rejectSuggestion.mutate({ id: String(s.id) }, {
                            onSuccess: () => toast.show(t.brain.suggestionRejected, 'info'),
                          })}
                          className="text-[10px] font-medium px-2 py-1 rounded-lg"
                          style={{ backgroundColor: theme.colors.down + '15', color: theme.colors.down }}
                        >
                          {t.brain.reject}
                        </button>
                        <button
                          onClick={() => approveSuggestion.mutate(String(s.id), {
                            onSuccess: () => toast.show(t.brain.suggestionApproved, 'success'),
                          })}
                          className="text-[10px] font-medium px-2 py-1 rounded-lg"
                          style={{ backgroundColor: theme.colors.up + '15', color: theme.colors.up }}
                        >
                          {t.brain.approve}
                        </button>
                      </div>
                    )}
                    {isApproved && (
                      <button
                        onClick={() => applySuggestion.mutate(String(s.id), {
                          onSuccess: () => toast.show(t.brain.appliedSuccess, 'success'),
                          onError: (err) => toast.show((err as Error)?.message || t.brain.appliedFailed, 'error'),
                        })}
                        className="text-[10px] font-bold px-3 py-1 rounded-lg"
                        style={{ backgroundColor: theme.colors.primary + '15', color: theme.colors.primary }}
                      >
                        {t.brain.applyToBrain}
                      </button>
                    )}
                  </div>
                </div>
              )
            })
          )}
        </div>
      )}

      {/* Audit tab */}
      {tab === 'audit' && (
        <div className="space-y-2">
          {auditList.length === 0 ? (
            <p className="text-sm text-center py-8" style={{ color: theme.colors.textSub }}>{t.brain.noAuditEvents}</p>
          ) : (
            auditList.map((event, i) => <AuditEntry key={i} event={event} />)
          )}
        </div>
      )}
    </div>
  )
}
