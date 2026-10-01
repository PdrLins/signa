"""Keep a Mac awake while the back-end runs (settings.keep_awake).

The scheduler runs scans at 6:00, 10:00, 12:00… and the brain watchdog every
15 minutes. When macOS idle-sleeps, the process is frozen: a scan "started"
at 6:00 really ran when someone woke the Mac, and connections died while it
slept ("Server disconnected"). `caffeinate -i -w <pid>` stops IDLE sleep for
as long as this process lives and ends by itself when it exits. It can't stop
sleep when the lid is closed (unless an external display and power are
connected). Does nothing on other systems or when caffeinate is missing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

from loguru import logger

_proc: subprocess.Popen | None = None


def start() -> bool:
    """Start caffeinate for this process. True when it is running."""
    global _proc
    from app.core.config import settings

    if not settings.keep_awake or sys.platform != "darwin":
        return False
    if _proc is not None and _proc.poll() is None:
        return True
    exe = shutil.which("caffeinate")
    if not exe:
        logger.warning("keep_awake: caffeinate not found; the Mac may sleep and pause scans")
        return False
    try:
        _proc = subprocess.Popen([exe, "-i", "-w", str(os.getpid())],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        logger.warning(f"keep_awake: could not start caffeinate: {e}")
        return False
    logger.info("keep_awake: Mac idle sleep blocked while Signa runs (lid-closed sleep still pauses it)")
    return True


def stop() -> None:
    global _proc
    if _proc is not None and _proc.poll() is None:
        _proc.terminate()
    _proc = None
