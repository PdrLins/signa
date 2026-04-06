'use client'

import { useEffect, useState } from 'react'
import { useTheme } from '@/hooks/useTheme'
import { useToastStore, type Toast, type ToastVariant } from '@/store/toastStore'
import { X, CheckCircle, AlertTriangle, AlertCircle, Info } from 'lucide-react'

function useVariantColor(variant: ToastVariant) {
  const theme = useTheme()
  const map: Record<ToastVariant, string> = {
    success: theme.colors.up,
    error: theme.colors.down,
    warning: theme.colors.warning,
    info: theme.colors.primary,
  }
  return map[variant]
}

const ICONS: Record<ToastVariant, typeof Info> = {
  success: CheckCircle,
  error: AlertCircle,
  warning: AlertTriangle,
  info: Info,
}

function ToastItem({ toast }: { toast: Toast }) {
  const theme = useTheme()
  const color = useVariantColor(toast.variant)
  const dismiss = useToastStore((s) => s.dismiss)
  const Icon = ICONS[toast.variant]
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    requestAnimationFrame(() => setVisible(true))
    const fadeTimer = setTimeout(() => setVisible(false), toast.duration - 300)
    return () => clearTimeout(fadeTimer)
  }, [toast.id, toast.duration])

  return (
    <div
      role={toast.variant === 'error' ? 'alert' : 'status'}
      aria-live={toast.variant === 'error' ? 'assertive' : 'polite'}
      className="flex items-center gap-3 px-4 py-3 rounded-xl max-w-sm w-full transition-all duration-300"
      style={{
        backgroundColor: theme.colors.surface,
        border: `1px solid ${color}30`,
        boxShadow: theme.isDark
          ? `0 8px 24px rgba(0,0,0,0.5), 0 0 0 1px ${color}20`
          : `0 8px 24px rgba(0,0,0,0.12), 0 0 0 1px ${color}15`,
        opacity: visible ? 1 : 0,
        transform: visible ? 'translateY(0)' : 'translateY(-12px)',
      }}
    >
      <Icon size={18} style={{ color, flexShrink: 0 }} />
      <p className="text-sm flex-1" style={{ color: theme.colors.text }}>
        {toast.message}
      </p>
      <button
        onClick={() => dismiss(toast.id)}
        className="p-0.5 rounded-md transition-opacity hover:opacity-70"
      >
        <X size={14} style={{ color: theme.colors.textSub }} />
      </button>
    </div>
  )
}

export function ToastContainer() {
  const toasts = useToastStore((s) => s.toasts)

  if (!toasts.length) return null

  return (
    <div className="fixed top-4 left-1/2 -translate-x-1/2 z-[100] flex flex-col items-center gap-2 pointer-events-none">
      {toasts.map((toast) => (
        <div key={toast.id} className="pointer-events-auto">
          <ToastItem toast={toast} />
        </div>
      ))}
    </div>
  )
}
