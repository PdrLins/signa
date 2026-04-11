"""Scan API routes — protected."""

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status

from app.core.dependencies import get_current_user
from app.db import queries
from app.models.signals import ScanTodayRecord
from app.services import scan_service, signal_service

router = APIRouter(prefix="/scans", tags=["Scans"])

# Scan type → human label + scheduled ET time
_SCAN_SLOTS = [
    ("PRE_MARKET", "Morning scan", "06:00"),
    ("MORNING", "Market open", "10:00"),
    ("MIDDAY", "Midday", "12:00"),
    ("PRE_CLOSE", "Pre-close", "15:00"),
    ("AFTER_CLOSE", "After close", "16:30"),
]


@router.get("")
async def get_scans(
    limit: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    """Get scan history."""
    scans = signal_service.get_scans(limit=limit)
    return {"scans": scans, "count": len(scans)}


@router.get("/today", response_model=list[ScanTodayRecord])
async def get_scans_today(user: dict = Depends(get_current_user)):
    """Get today's 4 scan slots — one per type, PENDING if not yet run.

    On weekends/holidays, returns all slots as CLOSED.
    """
    from zoneinfo import ZoneInfo

    et = ZoneInfo("America/New_York")
    now_et = datetime.now(et)
    is_market_day = now_et.weekday() < 5  # Mon=0 .. Fri=4

    # Use ET date for "today" — at 8pm+ ET the UTC date rolls to
    # tomorrow, which would make all of today's scans invisible.
    today_et = now_et.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start = today_et.astimezone(timezone.utc)

    scan_by_type: dict[str, dict] = {}
    # An active manual scan (Scan Now click) doesn't fit any of the 5
    # scheduled slots, so we surface it as a synthetic 6th row at the top
    # of the response while it's running. Without this, the schedule list
    # has no row to show a RUNNING/QUEUED status on, and the pulse animation
    # never fires when the user manually triggers a scan.
    manual_active: dict | None = None
    if is_market_day:
        recent_scans = signal_service.get_scans(limit=50)
        today_scans = [
            s for s in recent_scans
            if s.get("started_at") and s["started_at"] >= today_start.isoformat()
        ]
        for s in today_scans:
            st = s.get("scan_type")
            if st == "MANUAL":
                # Only surface manual scans when they're actively running.
                # Completed manual scans stay hidden so they don't overwrite
                # the slot for whatever scheduled scan covers the same time.
                if s.get("status") in ("RUNNING", "QUEUED") and manual_active is None:
                    manual_active = s
                continue
            if st and st not in scan_by_type:
                scan_by_type[st] = s

    result = []
    for scan_type, label, sched_time in _SCAN_SLOTS:
        if not is_market_day:
            result.append(ScanTodayRecord(
                scan_type=scan_type,
                label=label,
                scheduled_time=sched_time,
                status="CLOSED",
                is_market_day=False,
            ))
            continue

        existing = scan_by_type.get(scan_type)
        if existing:
            # Compute duration if both timestamps exist
            duration = None
            started = existing.get("started_at")
            completed = existing.get("completed_at")
            if started and completed:
                try:
                    from app.core.dates import parse_iso_utc
                    s = parse_iso_utc(started) if isinstance(started, str) else started
                    c = parse_iso_utc(completed) if isinstance(completed, str) else completed
                    if s is not None and c is not None:
                        duration = int((c - s).total_seconds())
                except Exception:
                    pass

            result.append(ScanTodayRecord(
                id=existing.get("id"),
                scan_type=scan_type,
                label=label,
                scheduled_time=sched_time,
                status=existing.get("status", "PENDING"),
                tickers_scanned=existing.get("tickers_scanned", 0),
                signals_found=existing.get("signals_found", 0),
                gems_found=existing.get("gems_found", 0),
                started_at=existing.get("started_at"),
                completed_at=existing.get("completed_at"),
                duration_seconds=duration,
            ))
        else:
            result.append(ScanTodayRecord(
                scan_type=scan_type,
                label=label,
                scheduled_time=sched_time,
            ))

    # Prepend the active manual scan (if any) so it shows at the top of
    # the schedule with a pulsing dot. The label is left blank — the
    # frontend renders it from i18n (`t.scans.manualScan`) so it stays
    # bilingual instead of being hardcoded English here.
    if manual_active:
        result.insert(0, ScanTodayRecord(
            id=manual_active.get("id"),
            scan_type="MANUAL",
            label="",  # frontend supplies label for MANUAL
            scheduled_time="",
            status=manual_active.get("status", "RUNNING"),
            tickers_scanned=manual_active.get("tickers_scanned", 0),
            signals_found=manual_active.get("signals_found", 0),
            gems_found=manual_active.get("gems_found", 0),
            started_at=manual_active.get("started_at"),
        ))

    return result


@router.post("/trigger")
async def trigger_scan(
    background_tasks: BackgroundTasks,
    scan_type: Literal["PRE_MARKET", "MORNING", "MIDDAY", "PRE_CLOSE", "AFTER_CLOSE", "MANUAL"] = Query("MANUAL"),
    user: dict = Depends(get_current_user),
):
    """Manually trigger a scan. Runs in the background — returns immediately.

    Use GET /scans/{scan_id}/progress to poll for real-time progress.
    Blocked if a scan is already running or queued.
    """
    from zoneinfo import ZoneInfo
    et_now = datetime.now(ZoneInfo("America/New_York"))
    if et_now.weekday() >= 5:  # Saturday=5, Sunday=6
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Markets are closed on weekends — scans are skipped to save AI credits.",
        )

    # Concurrency guard — reject if a scan is already running
    recent = queries.get_scans(limit=5)
    active = [s for s in recent if s.get("status") in ("RUNNING", "QUEUED")]
    if active:
        active_id = active[0].get("id")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A scan is already in progress ({active_id}). Wait for it to complete.",
        )

    # Create the scan record first so we can return the ID
    scan = queries.insert_scan({
        "scan_type": scan_type,
        "status": "QUEUED",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "progress_pct": 0,
        "phase": "queued",
        "triggered_by": "manual",
    })
    scan_id = scan.get("id")

    if not scan_id:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create scan")

    # Run scan in background with the pre-created scan_id
    background_tasks.add_task(scan_service.run_scan, scan_type, scan_id)
    return {
        "scan_id": scan_id,
        "status": "QUEUED",
        "message": f"{scan_type} scan triggered — poll /scans/{scan_id}/progress for updates",
    }


@router.get("/{scan_id}/progress")
async def get_scan_progress(
    scan_id: UUID,
    user: dict = Depends(get_current_user),
):
    """Get real-time scan progress — frontend polls this every 2-3 seconds.

    Returns:
        scan_id, status, progress_pct (0-100), phase, current_ticker,
        candidates, signals_found, gems_found
    """
    scan = queries.get_scan_by_id(str(scan_id))
    if not scan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scan not found")

    return {
        "scan_id": scan.get("id"),
        "status": scan.get("status", "RUNNING"),
        "progress_pct": scan.get("progress_pct", 0),
        "phase": scan.get("phase", "starting"),
        "current_ticker": scan.get("current_ticker", ""),
        "candidates": scan.get("candidates", 0),
        "tickers_scanned": scan.get("tickers_scanned", 0),
        "signals_found": scan.get("signals_found", 0),
        "gems_found": scan.get("gems_found", 0),
        "started_at": scan.get("started_at"),
        "completed_at": scan.get("completed_at"),
        "error_message": scan.get("error_message"),
    }
