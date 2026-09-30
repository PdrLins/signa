export type AccessLevel = 'free' | 'premium' | 'owner'

export interface FeatureInfo {
  key: string
  min_level: AccessLevel
  description: string
}

export interface SlotSummary {
  used: number
  /** null = unlimited */
  limit: number | null
  remaining: number | null
}

/** GET /auth/me — the server's answer to "what can this user use?". */
export interface MeResponse {
  user_id: string
  username: string | null
  access_level: AccessLevel
  /** Every area / action key this user may use. */
  features: string[]
  /** Every known key with its minimum level (for "Needs premium" badges). */
  catalog: FeatureInfo[]
  slots: SlotSummary
}
