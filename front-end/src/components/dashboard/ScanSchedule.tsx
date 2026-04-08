'use client'

import { useTheme } from '@/hooks/useTheme'
import { useScansToday } from '@/hooks/useScans'
import { useI18nStore } from '@/store/i18nStore'
import { Card } from '@/components/ui/Card'
import { Skeleton } from '@/components/ui/Skeleton'
import { interpolate } from '@/lib/utils'

export function ScanSchedule() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const { data: scans, isLoading } = useScansToday()

  const statusColor: Record<string, string> = {
    COMPLETE: theme.colors.up,
    RUNNING: theme.colors.primary,
    QUEUED: theme.colors.primary,
    FAILED: theme.colors.down,
    CLOSED: theme.colors.textHint,
    PENDING: theme.colors.warning,
  }
  // Statuses that should pulse the dot (an active scan in progress).
  // Both RUNNING and QUEUED count — QUEUED is the brief moment between the
  // user clicking Scan Now and the worker picking the job up, and we want
  // the visual feedback immediately so it doesn't look frozen.
  const isActive = (status: string) => status === 'RUNNING' || status === 'QUEUED'

  const isWeekend = scans?.length ? scans[0].status === 'CLOSED' : false

  return (
    <Card>
      <p className="text-[11px] font-semibold uppercase tracking-wide mb-3" style={{ color: theme.colors.textSub }}>
        {t.scans.title}
      </p>

      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} width="100%" height={20} />
          ))}
        </div>
      ) : isWeekend ? (
        <div className="space-y-2">
          <p className="text-xs font-medium" style={{ color: theme.colors.textSub }}>
            {t.scans.marketsClosed}
          </p>
          {scans?.map((scan) => (
            <div key={scan.scan_type} className="flex items-center justify-between opacity-40">
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full" style={{ backgroundColor: theme.colors.textHint }} />
                <span className="text-xs" style={{ color: theme.colors.text }}>{scan.label}</span>
              </div>
              <span className="text-[11px]" style={{ color: theme.colors.textSub }}>{scan.scheduled_time}</span>
            </div>
          ))}
        </div>
      ) : !scans?.length ? (
        <p className="text-xs" style={{ color: theme.colors.textSub }}>{t.scans.noScans}</p>
      ) : (
        <div className="space-y-2">
          {scans.map((scan) => {
            const dotColor = statusColor[scan.status] || theme.colors.textHint
            // MANUAL scans come from the backend with an empty label so the
            // frontend can supply a translated one. All scheduled slots use
            // their server-supplied label as before.
            const displayLabel = scan.scan_type === 'MANUAL'
              ? (t.scans.manualScan ?? 'Manual scan')
              : scan.label

            return (
              <div key={`${scan.scan_type}-${scan.id ?? 'slot'}`} className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span
                    className="w-2 h-2 rounded-full"
                    style={{
                      backgroundColor: dotColor,
                      animation: isActive(scan.status) ? 'pulse 1.5s infinite' : 'none',
                    }}
                  />
                  <span className="text-xs" style={{ color: theme.colors.text }}>
                    {displayLabel}
                  </span>
                  {scan.status === 'COMPLETE' && scan.duration_seconds != null && (
                    <span className="text-[9px] tabular-nums" style={{ color: theme.colors.up }}>
                      {scan.duration_seconds}s
                    </span>
                  )}
                  {scan.status === 'FAILED' && (
                    <span className="text-[9px]" style={{ color: theme.colors.down }}>
                      {t.scans.failed}
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  {scan.status === 'COMPLETE' && scan.signals_found > 0 && (
                    <span className="text-[9px] tabular-nums" style={{ color: theme.colors.textHint }}>
                      {scan.gems_found > 0
                        ? interpolate(t.scans.signalCountGems, { count: scan.signals_found, gems: scan.gems_found })
                        : interpolate(t.scans.signalCount, { count: scan.signals_found })}
                    </span>
                  )}
                  <span className="text-[11px]" style={{ color: theme.colors.textSub }}>
                    {scan.scheduled_time}
                  </span>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </Card>
  )
}
