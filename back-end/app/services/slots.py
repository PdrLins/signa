"""Followed-stock slots: how many distinct symbols a user may follow.

A slot is one symbol in the user's holdings or watchlist (a symbol in both
counts once). The limit comes from the user's access level
(app.core.access.slot_limit): free 10, premium and owner unlimited.
"""

from __future__ import annotations

import asyncio
from typing import Iterable, Optional

from fastapi import HTTPException, status

from app.core.access import slot_limit, upgrade_hint
from app.db.supabase import get_client


def followed_symbols(user_id: str) -> set[str]:
    db = get_client()
    symbols: set[str] = set()
    for table in ("holdings", "watchlist"):
        try:
            rows = db.table(table).select("symbol").eq("user_id", user_id).execute().data or []
        except Exception:
            rows = []  # table missing (holdings before 010): counts as empty
        symbols.update(str(r["symbol"]).upper() for r in rows if r.get("symbol"))
    return symbols


def slot_summary(user: dict) -> dict:
    """{"used", "limit", "remaining"}; limit/remaining None = unlimited."""
    limit = slot_limit(user.get("access_level") or "free", int(user.get("slot_bonus") or 0))
    used = len(followed_symbols(user["user_id"]))
    return {"used": used, "limit": limit, "remaining": None if limit is None else max(0, limit - used)}


def check_new_symbols(user: dict, symbols: Iterable[str]) -> None:
    """403 if following `symbols` would exceed the limit. Symbols the user
    already follows don't need a slot. Body:
    {"detail": {"code": "slot_limit", "limit": 10, "used": 10, "requested": 1,
                "message": str,
                "upgrade": {"feature": "system.unlimited_slots", "plan": "premium"}}}"""
    limit: Optional[int] = slot_limit(user.get("access_level") or "free", int(user.get("slot_bonus") or 0))
    if limit is None:
        return
    current = followed_symbols(user["user_id"])
    new = {s.upper() for s in symbols} - current
    if new and len(current) + len(new) > limit:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "slot_limit", "limit": limit, "used": len(current),
                    "requested": len(new),
                    "message": f"Your plan follows up to {limit} stocks.",
                    "upgrade": upgrade_hint("system.unlimited_slots")},
        )


async def check_new_symbols_async(user: dict, symbols: Iterable[str]) -> None:
    await asyncio.to_thread(check_new_symbols, user, list(symbols))
