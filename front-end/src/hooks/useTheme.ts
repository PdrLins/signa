import { useThemeStore } from '@/store/themeStore'

export function useTheme() {
  return useThemeStore((state) => state.theme)
}
