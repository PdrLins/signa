'use client'

import { useBrainStore } from '@/store/brainStore'
import { BrainLocked } from '@/components/brain/BrainLocked'
import { BrainEditor } from '@/components/brain/BrainEditor'

export default function BrainPage() {
  const isUnlocked = useBrainStore((s) => s.isUnlocked)
  return isUnlocked ? <BrainEditor /> : <BrainLocked />
}
