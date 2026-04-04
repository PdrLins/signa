'use client'

import { BucketSplit } from '@/components/dashboard/BucketSplit'
import { ScanSchedule } from '@/components/dashboard/ScanSchedule'
import { TelegramStatus } from '@/components/dashboard/TelegramStatus'
import { AIUsage } from '@/components/dashboard/AIUsage'

export function Sidebar() {
  return (
    <aside className="hidden md:flex flex-col gap-3 w-[288px] shrink-0">
      <BucketSplit />
      <ScanSchedule />
      <TelegramStatus />
      <AIUsage />
    </aside>
  )
}
