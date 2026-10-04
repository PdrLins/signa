"""Thread pools.

All blocking work (Supabase via supabase-py, yfinance, bcrypt) runs in
threads. Python's default pool is tiny on a small server (min(32, cpus + 4):
5 threads on 1 vCPU), so one slow Yahoo call or a scheduled job made every
API request wait. Two pools fix that:

  default pool   API requests (asyncio.to_thread / run_in_executor(None)),
                 REQUEST_WORKERS threads, installed at startup (install()).
  job pool       scheduled jobs (in_job_pool), JOB_WORKERS threads, so a
                 long quotes/snapshot run can never take the request threads.

Threads here mostly wait on the network, so they are cheap.
"""

from __future__ import annotations

import asyncio
import functools
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

REQUEST_WORKERS = 32
JOB_WORKERS = 4
YAHOO_DOWNLOAD_THREADS = 8   # parallel symbol requests inside one yf.download

JOB_POOL = ThreadPoolExecutor(max_workers=JOB_WORKERS, thread_name_prefix="job")


def install(loop: asyncio.AbstractEventLoop | None = None) -> None:
    """Give the running loop a bigger default pool (call once at startup)."""
    loop = loop or asyncio.get_running_loop()
    loop.set_default_executor(ThreadPoolExecutor(max_workers=REQUEST_WORKERS, thread_name_prefix="io"))


async def in_job_pool(fn: Callable, *args: Any, **kwargs: Any) -> Any:
    """asyncio.to_thread, on the scheduled-jobs pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(JOB_POOL, functools.partial(fn, *args, **kwargs))


def download_threads(n: int) -> int | bool:
    """yf.download(threads=...): parallel requests for several symbols (yfinance
    makes one HTTP request per symbol); False for a single symbol."""
    return min(YAHOO_DOWNLOAD_THREADS, n) if n > 1 else False
