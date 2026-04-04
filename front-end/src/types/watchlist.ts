export interface WatchlistItem {
  id: string
  symbol: string
  added_at: string
  notes: string | null
}

export interface WatchlistResponse {
  items: WatchlistItem[]
  count: number
}

export interface WatchlistAddRequest {
  notes?: string
}
