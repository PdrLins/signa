"""Alert queue processor — sends pending alerts via Telegram."""

from datetime import datetime, timezone

from loguru import logger

from app.core.config import settings
from app.db import queries
from app.notifications.telegram_bot import send_message


async def process_pending_alerts() -> int:
    """Send all pending alerts in the queue.

    Returns the number of alerts sent.
    """
    pending = queries.get_pending_alerts()
    if not pending:
        return 0

    sent_count = 0
    for alert in pending:
        alert_id = alert.get("id")
        message = alert.get("message", "")

        success = await send_message(settings.telegram_chat_id, message)

        if success:
            queries.update_alert_status(alert_id, status="SENT", sent_at=datetime.now(timezone.utc))
            sent_count += 1
        else:
            queries.update_alert_status(alert_id, status="FAILED")
            logger.warning(f"Failed to send alert {alert_id}")

    if sent_count:
        logger.info(f"Dispatched {sent_count}/{len(pending)} alerts")

    return sent_count
