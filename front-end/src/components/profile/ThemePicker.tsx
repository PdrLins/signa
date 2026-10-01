'use client'

import { Check } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useI18nStore } from '@/store/i18nStore'
import { useThemeStore } from '@/store/themeStore'
import { themes, type ThemeId } from '@/lib/themes'

const THEME_IDS = Object.keys(themes) as ThemeId[]

/** Theme swatches (each drawn in its own colours). Saved on this device and
 *  synced to the account (themeStore). */
export function ThemePicker() {
  const theme = useTheme()
  const t = useI18nStore((s) => s.t)
  const setTheme = useThemeStore((s) => s.setTheme)
  return (
    <div role="radiogroup" aria-label={t.settings.themeLabel} className="grid grid-cols-2 sm:grid-cols-3 gap-2">
      {THEME_IDS.map((id) => {
        const th = themes[id]
        const active = theme.id === id
        return (
          <button key={id} type="button" role="radio" aria-checked={active} onClick={() => setTheme(id)}
            className="relative text-left rounded-xl p-3 min-h-[60px] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
            style={{
              backgroundColor: th.colors.bg,
              border: active ? `2px solid ${th.colors.primary}` : `1px solid ${theme.colors.border}`,
              outlineColor: theme.colors.primary,
            }}>
            {active && (
              <span className="absolute top-2 right-2 w-5 h-5 rounded-full flex items-center justify-center"
                style={{ backgroundColor: th.colors.primary, color: th.colors.bg }} aria-hidden="true">
                <Check size={12} />
              </span>
            )}
            <span className="block text-[13px] font-semibold" style={{ color: th.colors.text }}>{th.name}</span>
            <span className="flex gap-1.5 mt-2" aria-hidden="true">
              {[th.colors.primary, th.colors.up, th.colors.down, th.colors.warning].map((c, i) => (
                <span key={`${c}-${i}`} className="w-3.5 h-3.5 rounded-full" style={{ backgroundColor: c }} />
              ))}
            </span>
          </button>
        )
      })}
    </div>
  )
}
