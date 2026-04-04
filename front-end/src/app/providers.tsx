'use client'

import { useEffect } from 'react'
import { useThemeStore } from '@/store/themeStore'
import { useAuthStore } from '@/store/authStore'
import { QueryProvider } from '@/components/providers/QueryProvider'
import { ErrorBoundary } from '@/components/providers/ErrorBoundary'

function StoreInitializer() {
  const initTheme = useThemeStore((s) => s.initialize)
  const initAuth = useAuthStore((s) => s.initialize)

  useEffect(() => {
    initTheme()
    initAuth()
  }, [initTheme, initAuth])

  return null
}

function ThemeApplicator({ children }: { children: React.ReactNode }) {
  const theme = useThemeStore((s) => s.theme)

  useEffect(() => {
    const html = document.documentElement
    if (theme.isDark) {
      html.classList.add('dark')
      html.style.colorScheme = 'dark'
    } else {
      html.classList.remove('dark')
      html.style.colorScheme = 'light'
    }
  }, [theme.isDark])

  return (
    <div
      className="min-h-screen transition-colors duration-200"
      style={{ backgroundColor: theme.colors.bg, color: theme.colors.text }}
    >
      {children}
    </div>
  )
}

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ErrorBoundary>
      <QueryProvider>
        <StoreInitializer />
        <ThemeApplicator>{children}</ThemeApplicator>
      </QueryProvider>
    </ErrorBoundary>
  )
}
