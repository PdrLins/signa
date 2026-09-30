// Transactions — manual entry and CSV import (back-end/app/api/v1/transactions.py).

export type TxType = 'buy' | 'sell' | 'dividend' | 'deposit' | 'withdrawal' | 'split' | 'fee'
export const TX_TYPES: TxType[] = ['buy', 'sell', 'dividend', 'deposit', 'withdrawal', 'split', 'fee']

export interface Transaction {
  id: string
  account_id: string | null
  account_name: string | null
  symbol: string | null
  type: TxType
  /** YYYY-MM-DD */
  trade_date: string
  quantity: number | null
  price: number | null
  /** Always positive; the direction comes from `type`. */
  amount: number | null
  currency: string | null
  fee: number | null
  note: string | null
  source: 'manual' | 'csv'
  import_batch_id: string | null
  created_at: string
}

export interface TransactionFilters {
  account_id?: string
  symbol?: string
  type?: TxType
  from?: string
  to?: string
  limit?: number
  offset?: number
}

export interface TransactionsResponse {
  items: Transaction[]
  count: number
  total: number
  limit: number
  offset: number
  has_more: boolean
}

export interface TransactionInput {
  account_id?: string | null
  symbol?: string | null
  type?: TxType
  trade_date?: string
  quantity?: number | null
  price?: number | null
  amount?: number | null
  currency?: string | null
  fee?: number | null
  note?: string | null
}

export interface RowError {
  field: string
  code: string
  message: string
}

export interface ImportSummary {
  rows: number
  valid: number
  invalid: number
  by_type: Partial<Record<TxType, number>>
  symbols: number
  date_range: { from: string; to: string } | null
  date_format: 'dmy' | 'mdy'
  delimiter: string
  ignored_columns: string[]
  accounts_to_create: string[]
}

export interface ImportRow {
  line: number
  status: 'ok' | 'error'
  data: (TransactionInput & { account_name?: string | null }) | null
  errors: RowError[]
}

export interface ImportDryRun {
  dry_run: true
  summary: ImportSummary
  rows: ImportRow[]
  errors: { line: number; errors: RowError[] }[]
}

export interface ImportResult {
  dry_run: false
  import_batch_id: string
  imported: number
  skipped: number
  accounts_created: { id: string; name: string }[]
  summary: ImportSummary
  errors: { line: number; errors: RowError[] }[]
}

export interface ImportOptions {
  create_missing_accounts?: boolean
  skip_errors?: boolean
  date_format?: 'auto' | 'dmy' | 'mdy'
}
