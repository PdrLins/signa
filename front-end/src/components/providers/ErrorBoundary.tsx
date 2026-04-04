'use client'

import { Component, type ReactNode } from 'react'
import { themes, DEFAULT_THEME } from '@/lib/themes'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
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
      const t = themes[DEFAULT_THEME]

      return (
        <div
          className="min-h-screen flex items-center justify-center px-4"
          style={{ backgroundColor: t.colors.bg }}
        >
          <div
            className="max-w-sm w-full rounded-2xl p-8 text-center"
            style={{
              backgroundColor: t.colors.surface,
              border: `0.5px solid ${t.colors.border}`,
              boxShadow: '0 4px 24px rgba(0,0,0,0.08)',
            }}
          >
            <div
              className="w-12 h-12 rounded-xl flex items-center justify-center text-lg mx-auto mb-4"
              style={{ backgroundColor: t.colors.down + '18', color: t.colors.down }}
            >
              !
            </div>
            <h2
              className="text-lg font-bold mb-2"
              style={{ color: t.colors.text }}
            >
              Something went wrong
            </h2>
            <p
              className="text-sm mb-6"
              style={{ color: t.colors.textSub }}
            >
              An unexpected error occurred. Please refresh the page or try again.
            </p>
            <button
              onClick={this.handleRetry}
              className="rounded-[11px] px-6 py-3 text-sm font-semibold text-white"
              style={{ backgroundColor: t.colors.primary }}
            >
              Retry
            </button>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}
