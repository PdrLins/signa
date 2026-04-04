'use client'

import { useTheme } from '@/hooks/useTheme'

type BadgeVariant =
  | 'gem' | 'buy' | 'confirmed' | 'safe'
  | 'sell' | 'cancelled'
  | 'hold' | 'weakening'
  | 'risk' | 'upgraded'
  | 'avoid'

interface BadgeProps {
  children: React.ReactNode
  variant?: BadgeVariant
}

export function Badge({ children, variant = 'hold' }: BadgeProps) {
  const theme = useTheme()

  const colorMap: Record<BadgeVariant, string> = {
    gem: theme.colors.up,
    buy: theme.colors.up,
    confirmed: theme.colors.up,
    safe: theme.colors.up,
    sell: theme.colors.down,
    cancelled: theme.colors.down,
    hold: theme.colors.warning,
    weakening: theme.colors.warning,
    risk: theme.colors.primary,
    upgraded: theme.colors.primary,
    avoid: theme.colors.textSub,
  }

  const color = colorMap[variant] || theme.colors.textSub

  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold whitespace-nowrap"
      style={{
        backgroundColor: color + '18',
        color,
      }}
    >
      {children}
    </span>
  )
}
