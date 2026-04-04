'use client'

import { themes, type ThemeId } from '@/lib/themes'
import { useThemeStore } from '@/store/themeStore'
import { useTheme } from '@/hooks/useTheme'
import { Check } from 'lucide-react'

const themeIds = Object.keys(themes) as ThemeId[]

interface ThemeSwitcherProps {
  compact?: boolean
}

export function ThemeSwitcher({ compact = false }: ThemeSwitcherProps) {
  const currentTheme = useTheme()
  const setTheme = useThemeStore((state) => state.setTheme)

  if (compact) {
    return (
      <div className="flex items-center gap-2">
        {themeIds.map((id) => {
          const t = themes[id]
          const isActive = currentTheme.id === id

          return (
            <button
              key={id}
              onClick={() => setTheme(id)}
              title={t.name}
              className="relative w-6 h-6 rounded-full transition-transform hover:scale-110"
              style={{
                backgroundColor: t.colors.primary,
                boxShadow: isActive
                  ? `0 0 0 2px ${currentTheme.colors.surface}, 0 0 0 4px ${t.colors.primary}`
                  : 'none',
              }}
            >
              {isActive && (
                <Check
                  size={12}
                  className="absolute inset-0 m-auto"
                  style={{ color: t.isDark ? '#000' : '#fff' }}
                />
              )}
            </button>
          )
        })}
      </div>
    )
  }

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
      {themeIds.map((id) => {
        const t = themes[id]
        const isActive = currentTheme.id === id

        return (
          <button
            key={id}
            onClick={() => setTheme(id)}
            className="relative text-left rounded-xl p-4 transition-all hover:scale-[1.02]"
            style={{
              backgroundColor: currentTheme.colors.surface,
              border: isActive
                ? `2px solid ${currentTheme.colors.primary}`
                : `1px solid ${currentTheme.colors.border}`,
            }}
          >
            {isActive && (
              <div
                className="absolute top-3 right-3 w-5 h-5 rounded-full flex items-center justify-center"
                style={{ backgroundColor: currentTheme.colors.primary }}
              >
                <Check size={12} style={{ color: '#fff' }} />
              </div>
            )}

            <p
              className="text-sm font-semibold mb-0.5"
              style={{ color: currentTheme.colors.text }}
            >
              {t.name}
            </p>
            <p
              className="text-xs mb-3"
              style={{ color: currentTheme.colors.textSub }}
            >
              {t.description}
            </p>

            <div className="flex gap-1.5">
              {[t.colors.primary, t.colors.accent, t.colors.up, t.colors.down].map(
                (color, i) => (
                  <span
                    key={i}
                    className="w-4 h-4 rounded-full"
                    style={{ backgroundColor: color }}
                  />
                )
              )}
            </div>
          </button>
        )
      })}
    </div>
  )
}
