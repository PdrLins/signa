'use client'

import { useState, useMemo } from 'react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Skeleton } from '@/components/ui/Skeleton'

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
          {Number(rule.weight_safe) > 0 && <span className="text-[10px]" style={{ color: theme.colors.up }}>{t.brain.safeWeight}: {String(rule.weight_safe)}</span>}
          {Number(rule.weight_risk) > 0 && <span className="text-[10px]" style={{ color: theme.colors.primary }}>{t.brain.riskWeight}: {String(rule.weight_risk)}</span>}
          {Boolean(rule.source_name) && (
            rule.source_url ? (
              <a href={String(rule.source_url)} target="_blank" rel="noopener noreferrer" className="text-[10px] underline" style={{ color: theme.colors.primary }} onClick={(e) => e.stopPropagation()}>
                {String(rule.source_name)}
              </a>
            ) : (
              <span className="text-[10px]" style={{ color: theme.colors.textHint }}>{String(rule.source_name)}</span>
            )
          )}
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

interface BrainRulesTabProps {
  rules: Record<string, unknown>[]
  isLoading: boolean
  ruleFilter: string
  onRuleFilterChange: (filter: string) => void
  onRuleSave: (ruleId: string, data: Record<string, unknown>) => void
}

export function BrainRulesTab({ rules, isLoading, ruleFilter, onRuleFilterChange, onRuleSave }: BrainRulesTabProps) {
  const theme = useTheme()
  const [editingRule, setEditingRule] = useState<string | null>(null)

  const filteredRules = useMemo(
    () => ruleFilter === 'ALL' ? rules : rules.filter((r) => r.rule_type === ruleFilter),
    [rules, ruleFilter]
  )
  const ruleTypes = useMemo(
    () => ['ALL', ...Array.from(new Set(rules.map((r) => r.rule_type as string)))],
    [rules]
  )
  const countByType = useMemo(() => {
    const map: Record<string, number> = { ALL: rules.length }
    for (const r of rules) {
      const t = r.rule_type as string
      map[t] = (map[t] ?? 0) + 1
    }
    return map
  }, [rules])

  return (
    <div role="tabpanel" id="tabpanel-rules" aria-labelledby="tab-rules" className="space-y-3">
      {/* Type filter */}
      <div className="flex flex-wrap gap-1.5">
        {ruleTypes.map((type) => (
          <button
            key={type}
            onClick={() => onRuleFilterChange(type)}
            className="px-2 py-1 rounded-lg text-[10px] font-medium"
            style={{
              backgroundColor: ruleFilter === type ? theme.colors.primary + '15' : theme.colors.surfaceAlt,
              color: ruleFilter === type ? theme.colors.primary : theme.colors.textSub,
            }}
          >
            {type} ({countByType[type] ?? 0})
          </button>
        ))}
      </div>

      {isLoading ? (
        <Skeleton width="100%" height={200} />
      ) : (
        filteredRules.map((rule) => (
          <div key={rule.id as string}>
            <RuleCard rule={rule} onEdit={() => setEditingRule(editingRule === rule.id ? null : rule.id as string)} />
            {editingRule === rule.id && (
              <RuleEditForm
                rule={rule}
                onSave={(data) => { onRuleSave(rule.id as string, data); setEditingRule(null) }}
                onCancel={() => setEditingRule(null)}
              />
            )}
          </div>
        ))
      )}
    </div>
  )
}
