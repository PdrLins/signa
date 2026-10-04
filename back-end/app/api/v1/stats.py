"""User settings (theme, language) — GET/PUT /stats/user-settings.

The path is historical (clients already call it); the brain's stats routes
moved to Signa Advisor.
"""

import asyncio

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from typing import Optional

from app.core.dependencies import get_current_user
from app.db import queries

router = APIRouter(prefix="/stats", tags=["Stats"])


class UserSettingsUpdate(BaseModel):
    theme: Optional[str] = Field(None, pattern=r"^(evergreen|inkgold|daylight|slate|applestocks|robinhood|wealthsimple|bloomberg|webull|etrade)$")
    language: Optional[str] = Field(None, pattern=r"^(en|pt)$")


@router.get("/user-settings")
async def get_user_settings(user: dict = Depends(get_current_user)):
    """Get current user's settings (theme, language)."""
    return await asyncio.to_thread(queries.get_user_settings, user["user_id"])


@router.put("/user-settings")
async def update_user_settings(body: UserSettingsUpdate, user: dict = Depends(get_current_user)):
    """Update current user's settings."""
    updates = body.model_dump(exclude_none=True)
    # The owner's language also drives the Telegram bot's shared messages.
    if "language" in updates and user.get("access_level") == "owner":
        from app.core.config import settings
        settings.language = updates["language"]
    if not updates:
        return await asyncio.to_thread(queries.get_user_settings, user["user_id"])
    return await asyncio.to_thread(queries.update_user_settings, user["user_id"], updates)
