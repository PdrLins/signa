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

    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    scan_by_type: dict[str, dict] = {}
    if is_market_day:
        recent_scans = signal_service.get_scans(limit=50)
        today_scans = [
            s for s in recent_scans
            if s.get("started_at") and s["started_at"] >= today_start.isoformat()
        ]
        for s in today_scans:
            st = s.get("scan_type")
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
            result.append(ScanTodayRecord(
                id=existing.get("id"),
                scan_type=scan_type,
                label=label,
                scheduled_time=sched_time,
                status=existing.get("status", "PENDING"),
                tickers_scanned=existing.get("tickers_scanned", 0),
                signals_found=existing.get("signals_found", 0),
                gems_found=existing.get("gems_found", 0),
                completed_at=existing.get("completed_at"),
            ))
        else:
            result.append(ScanTodayRecord(
                scan_type=scan_type,
                label=label,
                scheduled_time=sched_time,
            ))
    return result


@router.post("/trigger")
async def trigger_scan(
    background_tasks: BackgroundTasks,
    scan_type: Literal["PRE_MARKET", "MORNING", "PRE_CLOSE", "AFTER_CLOSE"] = Query("MORNING"),
    user: dict = Depends(get_current_user),
):
    """Manually trigger a scan. Runs in the background — returns immediately.

    Use GET /scans/{scan_id}/progress to poll for real-time progress.
    """
    # Create the scan record first so we can return the ID
    scan = queries.insert_scan({
        "scan_type": scan_type,
        "status": "QUEUED",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "progress_pct": 0,
        "phase": "queued",
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
