"""Structured API errors and the DB-call wrapper for the portfolio endpoints.

Every error body is {"detail": {"code": ..., "message": ..., **extra}} so web
and iOS clients can branch on `code` and show `message`.

`run_db(fn, *args)` runs a blocking query/service in a thread and maps DB
failures:
  * missing table / column (a migration not applied yet)
        -> 503 {"code": "migration_required", "migration": "013_portfolio_foundation.sql"}
  * anything else -> 503 {"code": "storage_unavailable"}
HTTPExceptions raised inside `fn` pass through untouched.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from fastapi import HTTPException, status
from loguru import logger

PORTFOLIO_MIGRATION = "013_portfolio_foundation.sql"
INSIGHTS_MIGRATION = "014_portfolio_insights.sql"

_MISSING_MARKERS = (
    "does not exist", "could not find the table", "could not find the", "42p01", "42703",
    "pgrst204", "pgrst205", "schema cache",
)


def api_error(code: str, message: str, http: int, **extra: Any) -> HTTPException:
    return HTTPException(status_code=http, detail={"code": code, "message": message, **extra})


def is_missing_schema(err: BaseException) -> bool:
    """True when a DB error means a table/column doesn't exist (migration missing)."""
    text = str(err).lower()
    return any(m in text for m in _MISSING_MARKERS)


def migration_required(migration: str = PORTFOLIO_MIGRATION) -> HTTPException:
    return api_error("migration_required",
                     f"This feature needs a database update — apply migration {migration}.",
                     status.HTTP_503_SERVICE_UNAVAILABLE, migration=migration)


class MigrationRequired(RuntimeError):
    """Raised by queries that detected the portfolio schema is missing."""


async def run_db(fn: Callable, *args: Any, **kwargs: Any) -> Any:
    return await run_db_for(PORTFOLIO_MIGRATION, fn, *args, **kwargs)


_TRANSIENT_MARKERS = ("server disconnected", "disconnected", "remoteprotocol", "connectionterminated",
                      "connection reset", "connection aborted", "eof occurred")


def is_transient(err: BaseException) -> bool:
    """A dropped/stale connection (Supabase closes idle HTTP/2 streams): worth a retry."""
    text = f"{type(err).__name__} {err}".lower()
    return any(m in text for m in _TRANSIENT_MARKERS)


async def run_db_for(migration: str, fn: Callable, *args: Any, **kwargs: Any) -> Any:
    """run_db, naming `migration` in a migration_required error. A dropped
    connection is retried up to twice with a fresh client before 503."""
    from app.db.supabase import reset_client

    for attempt in range(3):
        try:
            return await asyncio.to_thread(fn, *args, **kwargs)
        except HTTPException:
            raise
        except Exception as e:
            if attempt < 2 and is_transient(e) and not is_missing_schema(e):
                logger.info(f"portfolio: connection dropped in {getattr(fn, '__name__', fn)}, retrying ({attempt + 1}/2)")
                reset_client()
                await asyncio.sleep(0.2 * (attempt + 1))
                continue
            return _raise_db_error(migration, fn, e)


def _raise_db_error(migration: str, fn: Callable, e: Exception):
    try:
        raise e
    except HTTPException:
        raise
    except MigrationRequired:
        raise migration_required(migration)
    except Exception as e:
        if is_missing_schema(e):
            logger.warning(f"portfolio: schema missing in {getattr(fn, '__name__', fn)}: {e}")
            raise migration_required(migration)
        logger.warning(f"portfolio: DB call {getattr(fn, '__name__', fn)} failed: {e}")
        raise api_error("storage_unavailable", "Storage is unavailable, try again shortly.",
                        status.HTTP_503_SERVICE_UNAVAILABLE)
