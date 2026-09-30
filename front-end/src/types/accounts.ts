// People and accounts — user-created, user-named (back-end/app/api/v1/accounts.py).

export interface Person {
  id: string
  name: string
  color: string | null
  accounts_count: number
  created_at: string
}

export interface PeopleResponse {
  items: Person[]
  count: number
}

export interface Account {
  id: string
  name: string
  person_id: string | null
  person_name: string | null
  /** Tax type (TFSA, ROTH_IRA ...) — premium + CA/US only */
  account_type: string | null
  currency: string
  cash_balance: number
  holdings_count: number
  created_at: string
  updated_at: string
}

export interface AccountsResponse {
  items: Account[]
  count: number
  /** Types allowed for the user's country (empty outside CA/US). */
  account_types: { country: string | null; types: string[] }
}

export interface AccountInput {
  name?: string
  person_id?: string | null
  currency?: string
  cash_balance?: number
  account_type?: string | null
}

export interface PersonInput {
  name?: string
  color?: string | null
}

export interface AccountDeleteResult {
  deleted: true
  id: string
  moved_to: string | null
  moved_holdings: number
  merged_holdings: number
}
