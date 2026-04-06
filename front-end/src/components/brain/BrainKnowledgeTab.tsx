'use client'

import { useState } from 'react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Skeleton } from '@/components/ui/Skeleton'

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
        {entry.source_url ? (
          <a href={String(entry.source_url)} target="_blank" rel="noopener noreferrer" className="text-[10px] underline" style={{ color: theme.colors.primary }} onClick={(e) => e.stopPropagation()}>
            {String(entry.source_name)}
          </a>
        ) : (
          <span className="text-[10px]" style={{ color: theme.colors.textHint }}>{String(entry.source_name)}</span>
        )}
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

interface BrainKnowledgeTabProps {
  knowledge: Record<string, unknown>[]
  isLoading: boolean
  onKnowledgeSave: (knowledgeId: string, data: Record<string, unknown>) => void
}

export function BrainKnowledgeTab({ knowledge, isLoading, onKnowledgeSave }: BrainKnowledgeTabProps) {
  const [editingKnowledge, setEditingKnowledge] = useState<string | null>(null)

  return (
    <div role="tabpanel" id="tabpanel-knowledge" aria-labelledby="tab-knowledge" className="space-y-3">
      {isLoading ? (
        <Skeleton width="100%" height={200} />
      ) : (
        knowledge.map((entry) => (
          <div key={entry.id as string}>
            <KnowledgeCard entry={entry} onEdit={() => setEditingKnowledge(editingKnowledge === entry.id ? null : entry.id as string)} />
            {editingKnowledge === entry.id && (
              <KnowledgeEditForm
                entry={entry}
                onSave={(data) => { onKnowledgeSave(entry.id as string, data); setEditingKnowledge(null) }}
                onCancel={() => setEditingKnowledge(null)}
              />
            )}
          </div>
        ))
      )}
    </div>
  )
}
