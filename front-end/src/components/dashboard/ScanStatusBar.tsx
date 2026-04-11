'use client'

import { useTheme } from '@/hooks/useTheme'
import { useScansToday } from '@/hooks/useScans'
import { useI18nStore } from '@/store/i18nStore'
import { Skeleton } from '@/components/ui/Skeleton'

export function ScanStatusBar() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const { data: scans, isLoading } = useScansToday()

  const statusColor: Record<string, string> = {
    COMPLETE: theme.colors.up,
    RUNNING: theme.colors.primary,
    QUEUED: theme.colors.primary,
    FAILED: theme.colors.down,
    CLOSED: theme.colors.textHint,
    PENDING: theme.colors.textHint,
  }

  const isActive = (status: string) => status === 'RUNNING' || status === 'QUEUED'

  if (isLoading) {
    return <Skeleton width={320} height={20} borderRadius={8} />
  }

  if (!scans?.length) {
    return (
      <span className="text-[11px]" style={{ color: theme.colors.textHint }}>
        {t.scans?.noScans ?? 'No scans'}
      </span>
    )
  }

  const isWeekend = scans[0].status === 'CLOSED'

  return (
    <div className="flex items-center gap-3 flex-wrap">
      {isWeekend && (
        <span className="text-[10px] font-medium" style={{ color: theme.colors.textSub }}>
          {t.scans?.marketsClosed ?? 'Markets closed'}
        </span>
      )}
      {scans
        .filter((s) => s.scan_type !== 'MANUAL')
        .map((scan) => {
          const dotColor = statusColor[scan.status] || theme.colors.textHint
          const displayLabel = scan.label?.split(' ').slice(0, 2).join(' ') || scan.scan_type

          return (
            <div
              key={`${scan.scan_type}-${scan.id ?? 'slot'}`}
              className="flex items-center gap-1.5"
              style={{ opacity: isWeekend ? 0.4 : 1 }}
            >
              <span
                className="w-2 h-2 rounded-full shrink-0"
                style={{
                  backgroundColor: dotColor,
                  animation: isActive(scan.status) ? 'pulse 1.5s infinite' : 'none',
                }}
              />
              <span className="text-[10px] whitespace-nowrap" style={{ color: theme.colors.textSub }}>
                {displayLabel}
              </span>
              {scan.status === 'COMPLETE' && scan.duration_seconds != null && (
                <span className="text-[9px] tabular-nums" style={{ color: theme.colors.up }}>
                  {scan.duration_seconds}s
                </span>
              )}
              {scan.status === 'FAILED' && (
                <span className="text-[9px]" style={{ color: theme.colors.down }}>
                  {t.scans?.failed ?? 'failed'}
                </span>
              )}
              {scan.status === 'PENDING' && (
                <span className="text-[9px]" style={{ color: theme.colors.textHint }}>
                  {'\u2014'}
                </span>
              )}
            </div>
          )
        })}
      {/* Show manual scans if running */}
      {scans
        .filter((s) => s.scan_type === 'MANUAL' && isActive(s.status))
        .map((scan) => (
          <div
            key={`${scan.scan_type}-${scan.id ?? 'slot'}`}
            className="flex items-center gap-1.5"
          >
            <span
              className="w-2 h-2 rounded-full shrink-0"
              style={{
                backgroundColor: theme.colors.primary,
                animation: 'pulse 1.5s infinite',
              }}
            />
            <span className="text-[10px] whitespace-nowrap" style={{ color: theme.colors.textSub }}>
              {t.scans?.manualScan ?? 'Manual'}
            </span>
          </div>
        ))}
    </div>
  )
}
