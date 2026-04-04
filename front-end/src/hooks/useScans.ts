import { useQuery } from '@tanstack/react-query'
import { scansApi } from '@/lib/api'
import type { ScanRecord } from '@/types/scan'
import type { ScanTodayRecord } from '@/types/signal'

export function useScans() {
  return useQuery<ScanRecord[]>({
    queryKey: ['scans'],
    queryFn: async () => {
      const res = await scansApi.getAll()
      return res.scans
    },
    refetchInterval: 60 * 1000,
  })
}

export function useScansToday() {
  return useQuery<ScanTodayRecord[]>({
    queryKey: ['scans', 'today'],
    queryFn: () => scansApi.getToday(),
    refetchInterval: 60 * 1000,
  })
}
