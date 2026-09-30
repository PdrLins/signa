/**
 * Page → area feature key. The server owns who may use which key (GET
 * /auth/me); this map only says which key each page belongs to. Longest
 * matching prefix wins.
 */
const ROUTE_AREAS: [string, string][] = [
  ['/home', 'area.home'],
  ['/insights', 'area.insights'],
  ['/coming-up', 'area.coming_up'],
  ['/profile', 'area.profile'],
  ['/today', 'area.today'],
  ['/overview', 'area.today'],
  ['/signals', 'area.signals'],
  ['/check', 'area.check'],
  ['/positions', 'area.positions'],
  ['/brain/performance', 'area.positions'],
  ['/performance', 'area.performance'],
  ['/brain', 'area.brain'],
  ['/holdings', 'area.holdings'],
  ['/stocks', 'area.stock'],
  ['/dividends', 'area.dividends'],
  ['/portfolio', 'area.holdings'],
  ['/watchlist', 'area.watchlist'],
  ['/how-it-works', 'area.how_it_works'],
  ['/settings', 'area.settings'],
  ['/integrations', 'area.integrations'],
  ['/logs', 'area.logs'],
]

export function areaForPath(pathname: string): string | null {
  let best: [string, string] | null = null
  for (const entry of ROUTE_AREAS) {
    const [prefix] = entry
    if ((pathname === prefix || pathname.startsWith(prefix + '/')) && (!best || prefix.length > best[0].length)) {
      best = entry
    }
  }
  return best ? best[1] : null
}

/** First page the user may open, in this order (everyone lands on /home). */
const HOME_CANDIDATES: [string, string][] = [
  ['/home', 'area.home'],
  ['/holdings', 'area.holdings'],
  ['/today', 'area.today'],
  ['/holdings', 'area.holdings'],
  ['/watchlist', 'area.watchlist'],
  ['/settings', 'area.settings'],
]

export function homePath(can: (feature: string) => boolean): string {
  return HOME_CANDIDATES.find(([, f]) => can(f))?.[0] ?? '/settings'
}

/** 403 codes a client turns into an upgrade moment (the upgrade sheet). */
export type LimitCode = 'slot_limit' | 'alert_limit'

/** Error thrown by the API client for 403 upgrade_required / slot_limit / alert_limit. */
export class ApiAccessError extends Error {
  constructor(
    message: string,
    public code: 'upgrade_required' | LimitCode | 'forbidden',
    public feature?: string,
    public limit?: number,
    /** slot_limit / alert_limit: what lifts the limit ({feature, plan: "premium"}) */
    public upgrade?: { feature: string; plan: string },
  ) {
    super(message)
    this.name = 'ApiAccessError'
  }
}

export function isLimitError(e: unknown): e is ApiAccessError & { code: LimitCode } {
  return e instanceof ApiAccessError && (e.code === 'slot_limit' || e.code === 'alert_limit')
}
