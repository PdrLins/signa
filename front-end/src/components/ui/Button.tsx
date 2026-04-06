'use client'

import { useTheme } from '@/hooks/useTheme'
import { cn } from '@/lib/utils'

interface ButtonProps {
  children: React.ReactNode
  variant?: 'primary' | 'secondary' | 'ghost'
  onClick?: (e: React.MouseEvent) => void
  fullWidth?: boolean
  disabled?: boolean
  type?: 'button' | 'submit'
}

export function Button({
  children,
  variant = 'primary',
  onClick,
  fullWidth = false,
  disabled = false,
  type = 'button',
}: ButtonProps) {
  const theme = useTheme()

  const styles: Record<string, React.CSSProperties> = {
    primary: {
      backgroundColor: disabled ? theme.colors.textHint : theme.colors.primary,
      color: theme.colors.surface,
    },
    secondary: {
      backgroundColor: theme.colors.surfaceAlt,
      color: theme.colors.primary,
    },
    ghost: {
      backgroundColor: 'transparent',
      color: theme.colors.primary,
    },
  }

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      aria-disabled={disabled ? 'true' : undefined}
      className={cn(
        'rounded-[11px] px-[18px] py-3 text-sm font-semibold transition-opacity',
        fullWidth && 'w-full',
        disabled ? 'cursor-not-allowed opacity-60' : 'hover:opacity-90 active:opacity-80'
      )}
      style={styles[variant]}
    >
      {children}
    </button>
  )
}
