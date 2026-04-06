'use client'

import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { maskIp, DEFAULT_TIMEZONE } from '@/lib/utils'

function AuditEntry({ event }: { event: Record<string, unknown> }) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const type = event.event_type as string
  const color = type.includes('GRANTED') ? theme.colors.up
    : type.includes('DENIED') || type.includes('LOCKED') ? theme.colors.down
    : theme.colors.primary

  const meta = (event.metadata ?? {}) as Record<string, unknown>
  const created = event.created_at ? new Date(event.created_at as string).toLocaleString('en-US', { timeZone: DEFAULT_TIMEZONE }) : ''

  return (
    <div className="rounded-xl px-4 py-3 space-y-1" style={{ backgroundColor: theme.colors.surfaceAlt, border: `1px solid ${theme.colors.border}` }}>
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold" style={{ color }}>{type}</span>
        <span className="text-[10px]" style={{ color: theme.colors.textHint }}>{created}</span>
      </div>
      {Boolean(meta.rule_name) && <p className="text-xs" style={{ color: theme.colors.text }}>{String(meta.rule_name)}</p>}
      {Boolean(meta.key_concept) && <p className="text-xs" style={{ color: theme.colors.text }}>{String(meta.key_concept)}</p>}
      {Array.isArray(meta.changed_fields) && (
        <p className="text-[10px]" style={{ color: theme.colors.textSub }}>{t.brain.changed}: {(meta.changed_fields as string[]).join(', ')}</p>
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
      <p className="text-[10px]" style={{ color: theme.colors.textHint }}>IP: {maskIp(event.ip_address as string)}</p>
    </div>
  )
}

interface BrainAuditTabProps {
  auditLog: Record<string, unknown>[]
}

export function BrainAuditTab({ auditLog }: BrainAuditTabProps) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)

  return (
    <div role="tabpanel" id="tabpanel-audit" aria-labelledby="tab-audit" className="space-y-2">
      {auditLog.length === 0 ? (
        <p className="text-sm text-center py-8" style={{ color: theme.colors.textSub }}>{t.brain.noAuditEvents}</p>
      ) : (
        auditLog.map((event, i) => <AuditEntry key={(event.id as string) ?? (event.created_at as string) ?? i} event={event} />)
      )}
    </div>
  )
}
