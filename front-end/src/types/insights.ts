// Response shapes for /api/v1/insights/* (back-end/app/api/v1/insights.py).
//
// Convention: any value the back-end does not store (or could not compute)
// is `null` — the UI must render "not available" instead of inventing it.
// Returns are PERCENT numbers unless the field name ends in `_frac`
// (candidate_outcomes stores decimal fractions: 0.05 = +5%).

// ── Shared ───────────────────────────────────────────────────

/** Machine-readable skip/enter reason. The UI formats `code` + `params`
 *  through the i18n dictionaries (t.reasons.*); `text` is the back-end's
 *  English rendering, used only as a fallback for unknown codes. */
export interface ReasonInfo {
  code: string
  params: Record<string, string | number | null>
  text: string
  raw: string | null
}

export type ModelSignal = 'BUY' | 'HOLD' | 'SELL' | 'AVOID' | string

// ── /insights/today ──────────────────────────────────────────

export interface BreakerInfo {
  state: 'normal' | 'paused'
  days_remaining: number | null
  tripped_at: string | null
  limit_pct: number
  pause_days: number
}

export interface TodayStatus {
  equity: number | null
  reset_at: string | null
  baseline: number | null
  change_pct: number | null
  spy_change_pct: number | null
  open_positions: number
  max_positions: number
  invested_usd: number
  invested_pct: number | null
  peak_equity: number | null
  drawdown_pct: number | null
  breaker: BreakerInfo
  ai_spend: { month_usd: number; budget_usd: number } | null
}

export interface ScanRef {
  id: string
  type: string | null
  status: string | null
  started_at: string | null
  completed_at: string | null
}

export interface ScanFunnel {
  universe: number | null
  candidates: number | null
  passed_filter: number | null
  ai_checked: number
  routine_buy: number
  decision_confirmed: number
  bought: number
}

export interface TodayDecision {
  symbol: string
  bucket: string | null
  decision: 'ENTER' | 'SKIP' | null
  reason: ReasonInfo | null
  action: string | null
  ai_status: string | null
  routine_signal: ModelSignal | null
  decision_signal: ModelSignal | null
  /** true = decision model vetoed, false = confirmed, null = not escalated */
  decision_overturned: boolean | null
  p_win: number | null
  rr: number | null
  score: number | null
}

export interface TodayPosition {
  id: string
  symbol: string
  entry_price: number | null
  current_price: number | null
  pnl_pct: number | null
  stop: number | null
  target: number | null
  /** where the price sits between stop (0) and target (1), clamped */
  progress: number | null
  days_held: number | null
  entry_date: string | null
  currency: string | null
}

export interface PortfolioRisk {
  n_positions: number
  beta: number | null
  vol_annual_pct: number | null
  avg_pairwise_corr: number | null
  max_pair: { a: string; b: string; corr: number } | null
  largest_cluster: { symbols: string[]; weight: number } | null
}

export interface RiskLimits {
  corr_max_pairwise: number
  corr_cluster_threshold: number
  corr_cluster_max: number
  max_drawdown_pct: number
  min_rr: number
  risk_per_trade_pct: number
}

export interface RunningScan {
  id: string
  type: string | null
  started_at: string | null
  progress_pct: number | null
  phase: string | null
}

export interface TodayInsights {
  as_of: string
  status: TodayStatus
  scan: ScanRef | null
  /** A scan still in flight (results below are from the previous one). */
  running_scan?: RunningScan | null
  /** False when the scan predates the brain decision log. */
  decisions_logged?: boolean
  funnel: ScanFunnel | null
  decisions: TodayDecision[]
  positions: TodayPosition[]
  risk: PortfolioRisk | null
  limits: RiskLimits
}

// ── /insights/performance ────────────────────────────────────

export interface StatSummary {
  n: number
  /** mean as a DECIMAL fraction (0.01 = +1%) */
  mean: number | null
  ci: [number, number] | null
  sufficient: boolean
  excludes_zero: 'pos' | 'neg' | null
}

export type VerdictState = 'insufficient' | 'positive' | 'negative' | 'inconclusive'

export interface EquityPoint {
  date: string
  /** % change since the first point (null when that series has no value) */
  signa: number | null
  spy: number | null
  xiu: number | null
}

export interface CohortRow extends StatSummary {
  key: 'entered' | 'vetoed' | 'rejected' | 'ai_not_called' | string
}

export interface CalibrationBucket {
  bucket: string
  n: number
  mean_p_win: number
  win_rate: number
  win_ci: [number, number] | null
}

export interface SkipGateRow extends StatSummary {
  reason: string
  verdict: 'costing' | 'protective' | 'inconclusive' | 'insufficient'
}

export interface PerformanceInsights {
  as_of: string
  threshold: number
  horizon: number
  verdict: {
    state: VerdictState
    n: number
    needed: number
    mean: number | null
    ci: [number, number] | null
  }
  counts: {
    tracked: number
    filled: number
    validated_buys: number
    closed_trades: number
  }
  equity_curve: {
    points: EquityPoint[]
    signa_pct: number | null
    spy_pct: number | null
    xiu_pct: number | null
  }
  cohorts: CohortRow[]
  calibration: {
    horizon: number
    n: number
    buckets: CalibrationBucket[]
    hidden_buckets: number
    brier: number | null
    brier_base_rate: number | null
  }
  overturn: {
    confirmed: StatSummary
    vetoed: StatSummary
    diff: number | null
    diff_ci: [number, number] | null
    direction: 'veto_helps' | 'veto_costs' | null
  }
  skip_reasons: SkipGateRow[]
}

// ── /insights/backtest ───────────────────────────────────────

export interface BacktestBand {
  band: string
  trades: number
  avg_excess_vs_spy_pct: number | null
  win_rate_pct: number | null
  expectancy_pct: number | null
}

export interface BacktestRun {
  name: string
  generated_at: string | null
  start: string | null
  end: string | null
  entry_rule: string | null
  n_symbols: number | null
  total_return_pct: number | null
  cagr_pct: number | null
  max_drawdown_pct: number | null
  sharpe: number | null
  trades: number
}

export interface BacktestInsights {
  runs: BacktestRun[]
  latest: {
    name: string
    start: string | null
    end: string | null
    benchmarks: Record<string, { total_return_pct: number | null; cagr_pct: number | null; max_drawdown_pct: number | null } | null>
    study_trades: number | null
    by_band: BacktestBand[]
    /** per technical-filter class/reason, when the report has it */
    by_filter: BacktestBand[] | null
    caveats: string[]
  } | null
}

// ── /insights/signal/{ticker} ────────────────────────────────

export interface TechCheck {
  key: 'above_sma200' | 'sma50_above_sma200' | 'rsi' | 'extension_sma50' | 'liquidity' | 'blockers' | string
  ok: boolean | null
  value: number | null
  limit: number | null
}

export interface ModelVerdict {
  signal: ModelSignal | null
  confidence: number | null
  p_win: number | null
  reasoning: string | null
}

export interface DecisionModelVerdict extends ModelVerdict {
  status: 'confirmed' | 'vetoed' | 'unavailable'
}

export interface RedFlag {
  text: string
  url: string | null
  severity: string | null
  category: string | null
}

export interface SignalTrail {
  symbol: string
  signal_id: string
  scan_id: string | null
  created_at: string
  company_name: string | null
  sector: string | null
  bucket: string | null
  action: string | null
  ai_status: string | null
  score: number | null
  price_at_signal: number | null
  decision: {
    decision: 'ENTER' | 'SKIP'
    reason: ReasonInfo | null
    decided_at: string | null
  } | null
  tech_filter: {
    passed: boolean | null
    reasons: string[]
    checks: TechCheck[]
  } | null
  grok: {
    summary: string | null
    score: number | null
    label: string | null
    citations: string[]
    x_citation_count: number | null
    red_flags: RedFlag[]
    error: string | null
  } | null
  routine: ModelVerdict | null
  decision_model: DecisionModelVerdict | null
  order: {
    ref_price: number | null
    fill: number | null
    stop: number | null
    target: number | null
    rr: number | null
    shares: number | null
    alloc_usd: number | null
    risk_usd: number | null
    risk_pct: number | null
    position_pct: number | null
    slippage_bps: number | null
    levels_source: string | null
    trade_id: string | null
  } | null
  correlation: {
    status: string | null
    rule: string | null
    max_corr: number | null
    max_corr_symbol: string | null
    corr: Record<string, number>
    max_pairwise: number | null
    cluster_threshold: number | null
  } | null
  sector_exposure: { sector: string; held: number; max: number } | null
  outcomes: {
    signal_at: string | null
    horizons: {
      days: number
      /** expected fill date (approx., trading days) */
      due_date: string | null
      fwd_ret_frac: number | null
      spy_ret_frac: number | null
      excess_ret_frac: number | null
      filled_at: string | null
    }[]
  } | null
}

// ── /insights/verdicts?ids=… ─────────────────────────────────

export interface SignalVerdict {
  ai_status: string | null
  ai_signal: string | null
  p_win: number | null
  routine_ai_signal: string | null
  decision_overturned: boolean | null
  tech_filter_passed: boolean | null
}
