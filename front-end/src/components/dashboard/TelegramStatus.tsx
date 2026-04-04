'use client'

import { useTheme } from '@/hooks/useTheme'
import { Card } from '@/components/ui/Card'
import { Send } from 'lucide-react'

export function TelegramStatus() {
  const theme = useTheme()

  return (
    <Card>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Send size={16} style={{ color: '#29B6F6' }} />
          <span className="text-xs font-semibold" style={{ color: theme.colors.text }}>
            Telegram
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full" style={{ backgroundColor: theme.colors.up }} />
          <span className="text-[11px]" style={{ color: theme.colors.up }}>
            Connected
          </span>
        </div>
      </div>
    </Card>
  )
}
