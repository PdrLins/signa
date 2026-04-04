'use client'

import { Component, type ReactNode } from 'react'
import { themes, DEFAULT_THEME } from '@/lib/themes'
import { useI18nStore } from '@/store/i18nStore'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
}

function ErrorFallback({ onRetry }: { onRetry: () => void }) {
  const t = useI18nStore((s) => s.t)
  const theme = themes[DEFAULT_THEME]

  return (
    <div
      className="min-h-screen flex items-center justify-center px-4"
      style={{ backgroundColor: theme.colors.bg }}
    >
      <div
        className="max-w-sm w-full rounded-2xl p-8 text-center"
        style={{
          backgroundColor: theme.colors.surface,
          border: `0.5px solid ${theme.colors.border}`,
          boxShadow: '0 4px 24px rgba(0,0,0,0.08)',
        }}
      >
        <div
          className="w-12 h-12 rounded-xl flex items-center justify-center text-lg mx-auto mb-4"
          style={{ backgroundColor: theme.colors.down + '18', color: theme.colors.down }}
        >
          !
        </div>
        <h2
          className="text-lg font-bold mb-2"
          style={{ color: theme.colors.text }}
        >
          {t.error.title}
        </h2>
        <p
          className="text-sm mb-6"
          style={{ color: theme.colors.textSub }}
        >
          {t.error.description}
        </p>
        <button
          onClick={onRetry}
          className="rounded-[11px] px-6 py-3 text-sm font-semibold text-white"
          style={{ backgroundColor: theme.colors.primary }}
        >
          {t.error.retry}
        </button>
      </div>
    </div>
  )
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false }
  }

  static getDerivedStateFromError(): State {
    return { hasError: true }
  }

  handleRetry = () => {
    this.setState({ hasError: false })
  }

  render() {
    if (this.state.hasError) {
      return <ErrorFallback onRetry={this.handleRetry} />
    }

    return this.props.children
  }
}
