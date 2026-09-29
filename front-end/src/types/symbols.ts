// GET /api/v1/symbols/search — back-end/app/api/v1/symbols.py
export type SymbolType = 'stock' | 'etf' | 'crypto'

export interface SymbolMatch {
  symbol: string
  name: string | null
  /** Raw exchange code (Yahoo, e.g. "NMS", "TOR") or the stored label. */
  exchange: string | null
  /** Display label: "NASDAQ", "NYSE", "NYSE Arca", "TSX", "TSXV", "NEO", "OTC", "Crypto", "US". */
  exchange_label: string
  type: SymbolType
  /** "signa" = a symbol Signa already tracks; "yahoo" = found on Yahoo Finance. */
  source: 'signa' | 'yahoo'
}

export interface SymbolSearchResponse {
  query: string
  results: SymbolMatch[]
}
