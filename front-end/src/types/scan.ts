export interface ScanRecord {
  id: string
  scan_type: 'PRE_MARKET' | 'MORNING' | 'MIDDAY' | 'PRE_CLOSE' | 'AFTER_CLOSE' | 'MANUAL'
  started_at: string
  completed_at: string | null
  tickers_scanned: number
  signals_found: number
  gems_found: number
  status: 'RUNNING' | 'COMPLETE' | 'FAILED'
  error_message: string | null
  created_at: string
}

export interface ScansResponse {
  scans: ScanRecord[]
  count: number
}
