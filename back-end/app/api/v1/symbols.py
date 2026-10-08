"""Symbol search — ticker or company name, typo tolerant, any exchange. Protected.
Dual listings show the user's country first (profile country; Canada when unset).

  GET /api/v1/symbols/search?q=tesla&limit=8
    -> {"query": "tesla", "results": [{symbol, name, exchange, exchange_label, type, source}]}

Logic lives in app/services/symbol_search.py.
"""

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import get_current_user
from app.services import symbol_search

router = APIRouter(prefix="/symbols", tags=["Symbols"])


@router.get("/search")
async def search_symbols(
    q: str = Query("", max_length=200),
    limit: int = Query(8, ge=1, le=symbol_search.MAX_LIMIT),
    user: dict = Depends(get_current_user),
):
    """Suggestions for the Check-a-stock search box."""
    query = symbol_search.normalize_query(q)
    country = None
    if query:
        try:
            import asyncio

            from app.db import queries
            from app.core import user_cache
            uid = user["user_id"]
            country = ((await asyncio.to_thread(user_cache.get, uid, "settings",
                                                lambda: queries.get_profile_settings(uid))) or {}).get("country")
        except Exception:
            country = None
    results = await symbol_search.search(query, limit, country) if query else []
    return {"query": query, "results": results}
