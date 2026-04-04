'use client'

import { Badge } from '@/components/ui/Badge'

interface SignalBadgeProps {
  action: string
}

export function SignalBadge({ action }: SignalBadgeProps) {
  const variantMap: Record<string, 'buy' | 'sell' | 'hold' | 'avoid'> = {
    BUY: 'buy',
    SELL: 'sell',
    HOLD: 'hold',
    AVOID: 'avoid',
  }

  return <Badge variant={variantMap[action] || 'hold'}>{action}</Badge>
}
