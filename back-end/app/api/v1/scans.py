"""Scan API routes — protected."""

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from app.core.dependencies import get_current_user
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
    """Get today's 4 scan slots — one per type, PENDING if not yet run."""
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    recent_scans = signal_service.get_scans(limit=50)
    today_scans = [
        s for s in recent_scans
        if s.get("started_at") and s["started_at"] >= today_start.isoformat()
    ]
    # Index by scan_type (most recent wins)
    scan_by_type: dict[str, dict] = {}
    for s in today_scans:
        st = s.get("scan_type")
        if st and st not in scan_by_type:
            scan_by_type[st] = s

    result = []
    for scan_type, label, sched_time in _SCAN_SLOTS:
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
    """Manually trigger a scan. Runs in the background — returns immediately."""
    background_tasks.add_task(scan_service.run_scan, scan_type)
    return {
        "status": "RUNNING",
        "message": f"{scan_type} scan triggered successfully",
    }
