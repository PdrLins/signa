'use client'

import Link from 'next/link'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'

interface ErrorDisplayProps {
  message?: string
  onRetry?: () => void
  /** Renders full-screen (100vh) for root error / not-found pages */
  fullScreen?: boolean
}

export function ErrorDisplay({ message, onRetry, fullScreen = false }: ErrorDisplayProps) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: fullScreen ? '100vh' : '60vh',
        backgroundColor: fullScreen ? theme.colors.bg : undefined,
        color: theme.colors.text,
        padding: 24,
        textAlign: 'center',
      }}
    >
      <div
        style={{
          width: 56,
          height: 56,
          borderRadius: 28,
          backgroundColor: theme.colors.surfaceAlt,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: 24,
          fontWeight: 700,
          color: theme.colors.down,
          marginBottom: 16,
        }}
      >
        !
      </div>
      <h2 style={{ fontSize: fullScreen ? 20 : 18, fontWeight: 600, marginBottom: 8 }}>
        {t.error.title}
      </h2>
      <p
        style={{
          fontSize: 14,
          color: theme.colors.textSub,
          marginBottom: 24,
          maxWidth: 400,
        }}
      >
        {message || t.error.description}
      </p>
      {onRetry && (
        <button
          onClick={onRetry}
          style={{
            padding: '10px 24px',
            borderRadius: 8,
            border: 'none',
            backgroundColor: theme.colors.primary,
            color: theme.colors.surface,
            fontSize: 14,
            fontWeight: 500,
            cursor: 'pointer',
          }}
        >
          {t.error.tryAgain}
        </button>
      )}
    </div>
  )
}

interface NotFoundDisplayProps {
  fullScreen?: boolean
}

export function NotFoundDisplay({ fullScreen = true }: NotFoundDisplayProps) {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: fullScreen ? '100vh' : '60vh',
        backgroundColor: fullScreen ? theme.colors.bg : undefined,
        color: theme.colors.text,
        padding: 24,
        textAlign: 'center',
      }}
    >
      <div
        style={{
          fontSize: 64,
          fontWeight: 700,
          color: theme.colors.textHint,
          marginBottom: 8,
        }}
      >
        404
      </div>
      <h1 style={{ fontSize: 20, fontWeight: 600, marginBottom: 8 }}>
        {t.error.pageNotFound}
      </h1>
      <p
        style={{
          fontSize: 14,
          color: theme.colors.textSub,
          marginBottom: 24,
        }}
      >
        {t.error.pageNotFoundDesc}
      </p>
      <Link
        href="/overview"
        style={{
          padding: '10px 24px',
          borderRadius: 8,
          backgroundColor: theme.colors.primary,
          color: theme.colors.surface,
          fontSize: 14,
          fontWeight: 500,
          textDecoration: 'none',
        }}
      >
        {t.error.backToDashboard}
      </Link>
    </div>
  )
}
