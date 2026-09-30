// Profile, preferences and notification switches (back-end/app/api/v1/{profile,notifications}.py).
import type { AccessLevel, SlotSummary } from '@/types/access'

export type TaxView = 'before' | 'after'

/** GET / PUT /profile */
export interface Profile {
  user_id: string
  username: string | null
  display_name: string | null
  email: string | null
  /** ISO 3166-1 alpha-2, e.g. "CA" */
  country: string | null
  home_currency: string
  language: 'en' | 'pt'
  /** The effective value (after-tax only when available). */
  dividend_tax_view: TaxView
  dividend_tax_view_stored: TaxView
  /** premium AND country in CA/US */
  tax_view_available: boolean
  /** Opt-in benchmark symbol; null = Off */
  compare_index: string | null
  holdings_native_currency: boolean
  access_level: AccessLevel
  slots: SlotSummary
}

/** PUT /profile body — only the fields sent change; null clears. */
export interface ProfileUpdate {
  display_name?: string | null
  country?: string | null
  home_currency?: string
  language?: 'en' | 'pt'
  dividend_tax_view?: TaxView
  compare_index?: string | null
  holdings_native_currency?: boolean
}

/** GET /profile/options */
export interface ProfileOptions {
  countries: string[]
  currencies: string[]
  convertible_currencies: string[]
  languages: string[]
  compare_indexes: { symbol: string; name: string }[]
  tax_view_countries: string[]
}

export type NotificationKey =
  | 'exdiv_reminder'
  | 'dividend_paid'
  | 'dividend_change'
  | 'check_changed'
  | 'earnings'
  | 'big_move'
  | 'analyst_ratings'
  | 'economy'

export interface NotificationPref {
  enabled: boolean
  /** big_move only, 1–50 */
  threshold_pct?: number
}

/** GET / PUT /notifications/prefs */
export interface NotificationPrefsResponse {
  prefs: Record<NotificationKey, NotificationPref>
  is_default: boolean
  updated_at: string | null
}

export type NotificationPrefsUpdate = Partial<Record<NotificationKey, Partial<NotificationPref>>>
