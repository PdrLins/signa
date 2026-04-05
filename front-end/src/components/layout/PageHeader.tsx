'use client'

import { useRouter } from 'next/navigation'
import { useTheme } from '@/hooks/useTheme'
import { ArrowLeft } from 'lucide-react'

interface PageHeaderProps {
  title: string
  subtitle?: string
  children?: React.ReactNode
}

export function PageHeader({ title, subtitle, children }: PageHeaderProps) {
  const theme = useTheme()
  const router = useRouter()

  return (
    <div className="flex items-start justify-between gap-4">
      <div className="flex items-center gap-3">
        <button
          onClick={() => router.back()}
          className="p-1.5 rounded-lg transition-opacity hover:opacity-70 shrink-0"
          style={{ color: theme.colors.textSub }}
        >
          <ArrowLeft size={20} />
        </button>
        <div>
          <h1 className="text-2xl font-bold" style={{ color: theme.colors.text }}>{title}</h1>
          {subtitle && (
            <p className="text-sm mt-1" style={{ color: theme.colors.textSub }}>{subtitle}</p>
          )}
        </div>
      </div>
      {children}
    </div>
  )
}
