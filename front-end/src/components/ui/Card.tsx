'use client'

import { useTheme } from '@/hooks/useTheme'
import { cn } from '@/lib/utils'

interface CardProps {
  children: React.ReactNode
  className?: string
  onClick?: () => void
  padding?: string
}

export function Card({ children, className, onClick, padding = '16px' }: CardProps) {
  const theme = useTheme()

  return (
    <div
      className={cn(
        'rounded-[14px] overflow-hidden transition-transform',
        onClick && 'cursor-pointer hover:scale-[1.01] active:scale-[0.99]',
        className
      )}
      style={{
        backgroundColor: theme.colors.surface,
        border: `0.5px solid ${theme.colors.border}`,
        boxShadow: theme.isDark ? '0 2px 10px rgba(0,0,0,0.3)' : '0 2px 10px rgba(0,0,0,0.06)',
        padding,
      }}
      onClick={onClick}
    >
      {children}
    </div>
  )
}
