# Position Timeline — Implementation Plan

## What to build

A day-by-day trace of every brain position showing how the price, peak, trailing stop, and thesis evolved from entry to exit (or current state). The user clicks on any open or closed position in the brain performance page and sees a vertical timeline like:

```
ASML — Held 5 days, exited via Trailing Stop at +3.7%

 Apr 8   $1,417.74  Entry (score 78, Tier 1, target $1,480, stop $1,350)
 Apr 8   $1,430.00  Hold — P&L +0.9%, thesis: valid
 Apr 9   $1,460.00  Peak updated — trailing activated at $1,416
 Apr 9   $1,489.90  New peak — trail rises to $1,445, target suppressed (< 7d)
 Apr 10  $1,520.00  New peak — trail rises to $1,474
 Apr 10  $1,500.00  Hold — above trail ($1,474), thesis: valid
 Apr 11  $1,470.00  TRAILING STOP — sold at +3.7% (peak was $1,520)
```

Each row is one scan snapshot. Color-coded: green = new peak, gray = hold, yellow = thesis weakening, red = exit.

---

## Prompt for execution

Copy everything below this line and paste it as the prompt to Claude Code:

---

I need you to build the Position Timeline feature for Signa. This is a day-by-day trace of every brain position showing price, peak, trailing stop, and thesis evolution.

## CRITICAL — Read these files first

Before writing ANY code, read these files to understand the existing patterns:

**Backend:**
- `back-end/app/services/virtual_portfolio.py` — the `check_virtual_exits` function (around line 1530+) is where you'll INSERT snapshot rows. Read the trailing stop logic (peak_price tracking, trailing_active, trailing_stop_price). Also read `_enrich_open_trade` (around line 1848) for how open trades are enriched for the API.
- `back-end/app/services/virtual_portfolio.py` — the `get_virtual_summary` function (around line 1775) for how the stats endpoint returns brain data.
- `back-end/app/api/v1/stats.py` — existing endpoints pattern.
- `back-end/app/api/v1/brain.py` — existing brain endpoints pattern.
- `back-end/CLAUDE.md` — key thresholds and rules.

**Frontend:**
- `front-end/src/app/(dashboard)/brain/performance/page.tsx` — the brain performance page where open positions and closed trades are rendered. The timeline will be accessible from here (click on a position row to navigate).
- `front-end/src/lib/api.ts` — API client pattern. All calls go through this.
- `front-end/src/lib/i18n/en.json` and `pt.json` — i18n pattern. All strings must be bilingual.
- `front-end/CLAUDE.md` — MUST follow these rules (theme colors, i18n, no hardcoded strings/colors).

## Step 1 — Database migration

Create file: `back-end/migrations/004_position_snapshots.sql`

```sql
CREATE TABLE IF NOT EXISTS position_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trade_id UUID NOT NULL,
    symbol TEXT NOT NULL,
    scan_id UUID,
    snapshot_at TIMESTAMPTZ DEFAULT NOW(),
    current_price FLOAT,
    entry_price FLOAT,
    peak_price FLOAT,
    trailing_stop_price FLOAT,
    fixed_target FLOAT,
    fixed_stop FLOAT,
    pnl_pct FLOAT,
    thesis_status TEXT,
    days_held INT,
    event TEXT NOT NULL,  -- 'ENTRY', 'HOLD', 'PEAK_UPDATED', 'TRAILING_ACTIVATED', 'TARGET_SUPPRESSED', 'TRAILING_STOP', 'TARGET_HIT', 'STOP_HIT', 'THESIS_INVALIDATED', 'WATCHDOG_EXIT', 'TIME_EXPIRED', 'ROTATION'
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pos_snapshots_trade ON position_snapshots(trade_id);
CREATE INDEX IF NOT EXISTS idx_pos_snapshots_symbol ON position_snapshots(symbol);
CREATE INDEX IF NOT EXISTS idx_pos_snapshots_at ON position_snapshots(snapshot_at DESC);
```

Print this SQL for the user to run in Supabase Dashboard.

## Step 2 — Backend: Record snapshots in check_virtual_exits

In `back-end/app/services/virtual_portfolio.py`, inside the `check_virtual_exits` function:

### 2a. Add a snapshot helper at the top of the file (near the other helpers):

```python
def _record_position_snapshot(
    db, trade: dict, current_price: float, peak: float,
    trailing_stop_price: float | None, pnl_pct: float,
    days_held: int, event: str, notes: str = "",
    scan_id: str | None = None,
) -> None:
    """Append one row to position_snapshots. Non-blocking, never propagates errors."""
    try:
        db.table("position_snapshots").insert({
            "trade_id": trade["id"],
            "symbol": trade["symbol"],
            "scan_id": scan_id,
            "current_price": round(current_price, 2),
            "entry_price": float(trade["entry_price"]),
            "peak_price": round(peak, 2),
            "trailing_stop_price": round(trailing_stop_price, 2) if trailing_stop_price else None,
            "fixed_target": float(trade["target_price"]) if trade.get("target_price") else None,
            "fixed_stop": float(trade["stop_loss"]) if trade.get("stop_loss") else None,
            "pnl_pct": round(pnl_pct, 2),
            "thesis_status": trade.get("thesis_last_status"),
            "days_held": days_held,
            "event": event,
            "notes": notes[:300] if notes else None,
        }).execute()
    except Exception as e:
        logger.debug(f"Position snapshot failed for {trade.get('symbol')}: {e}")
```

### 2b. Record snapshots inside the check_virtual_exits loop

After ALL the exit logic is resolved for each trade (whether it exits or holds), insert a snapshot. The key insertion points:

1. **When an exit fires** (after the exit is written to DB, around the `db.table("virtual_trades").update(...)` calls): call `_record_position_snapshot(db, trade, current_price, peak, trailing_stop_price, pnl_pct, days_held, event=exit_reason, notes=...)`

2. **When a position HOLDS** (the `if not exit_reason: continue` path, but BEFORE the continue): call `_record_position_snapshot(db, trade, current_price, peak, trailing_stop_price, pnl_pct, days_held, event=event_type, notes=...)` where event_type is:
   - `"PEAK_UPDATED"` if current_price became the new peak this scan
   - `"TRAILING_ACTIVATED"` if trailing just became active this scan (peak crossed 3% threshold)
   - `"TARGET_SUPPRESSED"` if target was hit but suppressed by the holding period rule
   - `"HOLD"` otherwise (normal hold, nothing special happened)

**IMPORTANT**: The function must also accept `scan_id` as a parameter (thread it through from `run_scan`). Currently `check_virtual_exits` only takes `notifications` — add `scan_id: str | None = None` parameter and update the call site in `scan_service.py`.

### 2c. Record the ENTRY snapshot

In `process_virtual_trades`, right after a new brain position is inserted (the `db.table("virtual_trades").insert(...)` call around line 1376), record the entry snapshot:

```python
_record_position_snapshot(db, {"id": <new_trade_id>, "symbol": symbol, "entry_price": price, "target_price": target, "stop_loss": stop, "thesis_last_status": None}, price, price, None, 0.0, 0, "ENTRY", notes=f"Score {score}, Tier {brain_tier}")
```

Note: you'll need the new trade's ID. The insert returns it — capture `result = db.table(...).insert(...).execute()` and use `result.data[0]["id"]`.

## Step 3 — Backend: API endpoint

Add to `back-end/app/api/v1/brain.py` (or `stats.py` — wherever makes more sense with the existing pattern):

```python
@router.get("/positions/{symbol}/timeline")
async def get_position_timeline(
    symbol: str = Path(..., pattern=r"^[A-Z0-9.\-]{1,10}$"),
    user: dict = Depends(get_current_user),
):
    """Get the day-by-day timeline for a brain position (open or closed)."""
    db = get_client()
    
    # Get the trade(s) for this symbol — could be multiple (re-entries)
    trades = (
        db.table("virtual_trades")
        .select("id, symbol, entry_date, exit_date, entry_price, exit_price, "
                "entry_score, pnl_pct, exit_reason, status, target_price, "
                "stop_loss, peak_price, entry_thesis, bucket, entry_tier")
        .eq("source", "brain")
        .eq("symbol", symbol)
        .order("entry_date", desc=True)
        .execute()
    ).data or []
    
    if not trades:
        return {"trades": [], "snapshots": []}
    
    trade_ids = [t["id"] for t in trades]
    
    # Get all snapshots for these trades
    snapshots = (
        db.table("position_snapshots")
        .select("*")
        .in_("trade_id", trade_ids)
        .order("snapshot_at")
        .execute()
    ).data or []
    
    return {"trades": trades, "snapshots": snapshots}
```

## Step 4 — Frontend: API client

Add to `front-end/src/lib/api.ts` in the brain or stats API section:

```typescript
getPositionTimeline: (symbol: string) => get<{
    trades: Array<{
        id: string
        symbol: string
        entry_date: string
        exit_date: string | null
        entry_price: number
        exit_price: number | null
        entry_score: number
        pnl_pct: number | null
        exit_reason: string | null
        status: string
        target_price: number | null
        stop_loss: number | null
        peak_price: number | null
        entry_thesis: string | null
        bucket: string
        entry_tier: number | null
    }>
    snapshots: Array<{
        id: string
        trade_id: string
        symbol: string
        snapshot_at: string
        current_price: number
        entry_price: number
        peak_price: number
        trailing_stop_price: number | null
        fixed_target: number | null
        fixed_stop: number | null
        pnl_pct: number
        thesis_status: string | null
        days_held: number
        event: string
        notes: string | null
    }>
}>(`/brain/positions/${symbol}/timeline`),
```

## Step 5 — Frontend: Timeline page

Create: `front-end/src/app/(dashboard)/brain/positions/[symbol]/page.tsx`

This is a new page that shows the full timeline for a specific symbol.

### Layout:

```
← Back to Brain Performance

ASML — CLOSED via Trailing Stop
Entry: Apr 8 at $1,417.74 (score 78, Tier 1)
Exit: Apr 11 at $1,470.00 (+3.7%)
Target: $1,480 | Stop: $1,350 | Peak: $1,520.00

[Timeline]
● Apr 8  10:03   $1,417.74   ENTRY        Score 78, Tier 1
● Apr 8  14:00   $1,430.00   HOLD         +0.9%, thesis valid
● Apr 8  16:00   $1,445.00   HOLD         +1.9%, thesis valid  
● Apr 9  10:00   $1,460.00   PEAK UPDATED +3.0%, trailing activated at $1,416
● Apr 9  14:00   $1,489.90   PEAK UPDATED trail → $1,445, target suppressed
● Apr 10 10:00   $1,520.00   PEAK UPDATED trail → $1,474
● Apr 10 14:00   $1,500.00   HOLD         above trail ($1,474)
● Apr 11 10:00   $1,470.00   TRAILING STOP sold at +3.7%

Entry Thesis:
"ASML has strong fundamentals with..."
```

### Visual design rules:
- Use `useTheme()` for ALL colors — never hardcode
- Use `useI18nStore()` for ALL text — add new keys with `?? 'fallback'` pattern
- Event dot colors from theme:
  - ENTRY: `theme.colors.primary`
  - HOLD: `theme.colors.textHint`
  - PEAK_UPDATED: `theme.colors.up`
  - TRAILING_ACTIVATED: `theme.colors.up`
  - TARGET_SUPPRESSED: `theme.colors.warning`
  - TRAILING_STOP / TARGET_HIT: `theme.colors.up` (green, it's a win exit)
  - STOP_HIT / WATCHDOG_EXIT: `theme.colors.down` (red, it's a loss exit)
  - THESIS_INVALIDATED: `theme.colors.warning`
- Vertical line connecting the dots: thin 1px line in `theme.colors.border`
- Each row shows: time, price, event badge, notes
- Price changes from previous row shown as delta (optional)
- Mobile responsive: the timeline stacks naturally

### If multiple trades exist for the same symbol (re-entries):
Show them as separate sections with a divider: "Trade #1 (closed)" / "Trade #2 (open)"

## Step 6 — Frontend: Link from brain performance page

In `front-end/src/app/(dashboard)/brain/performance/page.tsx`:

### 6a. Open positions — make each row clickable
The rows already have an onClick to expand. Add a "View timeline" link inside the expanded detail:

```tsx
<Link href={`/brain/positions/${vt.symbol}`}>
    <span className="text-[10px] font-medium" style={{ color: theme.colors.primary }}>
        View position timeline →
    </span>
</Link>
```

There's already a "View full signal →" link in the expanded view. Add the timeline link next to it.

### 6b. Closed trades — make each row clickable
Wrap each closed trade row in a `<Link href={/brain/positions/${rc.symbol}}>` so clicking navigates to the timeline.

## Step 7 — i18n

Add these keys to BOTH `en.json` and `pt.json` under the `howItWorks` section or a new `timeline` section:

**English (en.json):**
```json
"timeline": {
    "title": "Position Timeline",
    "backToPerformance": "Back to Brain Performance",
    "entryLabel": "Entry",
    "exitLabel": "Exit",
    "peakLabel": "Peak",
    "targetLabel": "Target",
    "stopLabel": "Stop",
    "tradeNumber": "Trade #{n}",
    "openTrade": "Currently Open",
    "closedTrade": "Closed",
    "closedVia": "Closed via {reason}",
    "entryThesis": "Entry Thesis",
    "noSnapshots": "No timeline data available yet. Snapshots are recorded on each scan.",
    "eventEntry": "Entry",
    "eventHold": "Hold",
    "eventPeakUpdated": "Peak Updated",
    "eventTrailingActivated": "Trailing Activated",
    "eventTargetSuppressed": "Target Suppressed",
    "eventTrailingStop": "Trailing Stop",
    "eventTargetHit": "Target Hit",
    "eventStopHit": "Stop Hit",
    "eventThesisInvalidated": "Thesis Invalidated",
    "eventWatchdog": "Watchdog Exit",
    "eventExpired": "Expired",
    "eventRotation": "Rotated Out",
    "viewTimeline": "View timeline"
}
```

**Portuguese (pt.json):**
```json
"timeline": {
    "title": "Linha do Tempo da Posicao",
    "backToPerformance": "Voltar para Performance do Brain",
    "entryLabel": "Entrada",
    "exitLabel": "Saida",
    "peakLabel": "Pico",
    "targetLabel": "Alvo",
    "stopLabel": "Stop",
    "tradeNumber": "Trade #{n}",
    "openTrade": "Aberto",
    "closedTrade": "Encerrado",
    "closedVia": "Encerrado via {reason}",
    "entryThesis": "Tese de Entrada",
    "noSnapshots": "Dados da linha do tempo ainda nao disponiveis. Snapshots sao gravados em cada varredura.",
    "eventEntry": "Entrada",
    "eventHold": "Manter",
    "eventPeakUpdated": "Novo Pico",
    "eventTrailingActivated": "Trailing Ativado",
    "eventTargetSuppressed": "Alvo Suprimido",
    "eventTrailingStop": "Trailing Stop",
    "eventTargetHit": "Alvo Atingido",
    "eventStopHit": "Stop Atingido",
    "eventThesisInvalidated": "Tese Invalidada",
    "eventWatchdog": "Saida Watchdog",
    "eventExpired": "Expirado",
    "eventRotation": "Rotacionado",
    "viewTimeline": "Ver linha do tempo"
}
```

## What NOT to do

- Don't change the trailing stop logic in check_virtual_exits — it's already built and working
- Don't change the exit priority order — stop > trailing > target > time
- Don't add new npm dependencies for the timeline visualization — build it with plain Tailwind + theme
- Don't create a separate timeline component library — one page.tsx file is enough
- Don't add snapshots for watchlist-track positions — brain only
- Don't retroactively generate snapshots for positions that existed before this feature — they'll start accumulating naturally from the next scan
- Don't batch the snapshot inserts — one per position per scan is fine (max ~20 inserts, each is tiny)

## Verification

After building:
1. Run the SQL migration in Supabase
2. Restart the backend
3. Trigger one scan
4. Check `position_snapshots` table — should have one row per open brain position with event='HOLD' or 'PEAK_UPDATED'
5. Navigate to the brain performance page, expand any position, click "View timeline"
6. The timeline page should show at least one snapshot row
7. After 2-3 more scans, the timeline should show multiple rows building up the history
8. Test with a closed trade that has snapshots — it should show the full entry-to-exit story
