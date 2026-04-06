'use client'

import { useEffect } from 'react'
import { useThemeStore } from '@/store/themeStore'
import { useAuthStore } from '@/store/authStore'
import { useI18nStore } from '@/store/i18nStore'
import { QueryProvider } from '@/components/providers/QueryProvider'
import { ErrorBoundary } from '@/components/providers/ErrorBoundary'
import { ToastContainer } from '@/components/ui/ToastContainer'

function StoreInitializer() {
  const initTheme = useThemeStore((s) => s.initialize)
  const loadTheme = useThemeStore((s) => s.loadFromServer)
  const initAuth = useAuthStore((s) => s.initialize)
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const initI18n = useI18nStore((s) => s.initialize)
  const loadI18n = useI18nStore((s) => s.loadFromServer)

  useEffect(() => {
    initTheme()
    initAuth()
    initI18n()
  }, [initTheme, initAuth, initI18n])

  // After auth, load settings from server (overrides localStorage)
  useEffect(() => {
    if (isAuthenticated) {
      loadTheme()
      loadI18n()
    }
  }, [isAuthenticated, loadTheme, loadI18n])

  return null
}

function ThemeApplicator({ children }: { children: React.ReactNode }) {
  const theme = useThemeStore((s) => s.theme)
  const locale = useI18nStore((s) => s.locale)

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

  useEffect(() => {
    document.documentElement.lang = locale === 'pt' ? 'pt-BR' : 'en-CA'
  }, [locale])

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
        <ThemeApplicator>
          <ToastContainer />
          {children}
        </ThemeApplicator>
      </QueryProvider>
    </ErrorBoundary>
  )
}
