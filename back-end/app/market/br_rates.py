"""Brazilian reference rates from Banco Central (SGS open data, no key).

  CDI    series 12   % per business day (e.g. 0.050788)
  SELIC  series 11   % per business day
  IPCA   series 433  % per month (dated the 1st of the month)

  series(name, since)  {date: value} from `since` to today. Cached
                       CACHE_TTL_S for everyone; one download at a time per
                       series; a failure is remembered FAIL_TTL_S and the last
                       good data keeps serving. Never raises.

SGS answers 404 when a range has no data (e.g. this month's IPCA before it's
published): that's an empty result, not an error. Requests are split into
10-year windows (the API's limit for daily series).
"""

from __future__ import annotations

import threading
import time
from datetime import date, timedelta

from loguru import logger

CODES = {"CDI": 12, "SELIC": 11, "IPCA": 433}
URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados"
CACHE_TTL_S = 6 * 3600
FAIL_TTL_S = 600
EARLIEST = date(2010, 1, 1)
WINDOW_DAYS = 3650

_data: dict[str, tuple[float, date, dict[date, float]]] = {}   # name -> (loaded at, since, values)
_failed_at: dict[str, float] = {}
_locks = {name: threading.Lock() for name in CODES}


def _parse(rows: list[dict]) -> dict[date, float]:
    out: dict[date, float] = {}
    for r in rows or []:
        try:
            d, m, y = (int(x) for x in str(r["data"]).split("/"))
            out[date(y, m, d)] = float(str(r["valor"]).replace(",", "."))
        except (KeyError, ValueError, TypeError):
            continue
    return out


def _download(code: int, since: date, until: date) -> dict[date, float]:
    import httpx
    out: dict[date, float] = {}
    start = since
    while start <= until:
        end = min(until, start + timedelta(days=WINDOW_DAYS))
        r = httpx.get(URL.format(code=code), timeout=20, params={
            "formato": "json", "dataInicial": start.strftime("%d/%m/%Y"), "dataFinal": end.strftime("%d/%m/%Y")})
        if r.status_code == 404:   # no values in this window
            pass
        else:
            r.raise_for_status()
            out.update(_parse(r.json()))
        start = end + timedelta(days=1)
    return out


def series(name: str, since: date) -> dict[date, float]:
    """{date: value} of a series from `since` (the cache may hold more)."""
    name = name.upper()
    if name not in CODES:
        return {}
    since = max(EARLIEST, since)
    hit = _data.get(name)
    fresh = hit and time.time() - hit[0] < CACHE_TTL_S and hit[1] <= since
    if fresh:
        return {d: v for d, v in hit[2].items() if d >= since}
    if time.time() - _failed_at.get(name, 0) < FAIL_TTL_S:
        return {d: v for d, v in (hit[2] if hit else {}).items() if d >= since}
    with _locks[name]:
        hit = _data.get(name)
        if hit and time.time() - hit[0] < CACHE_TTL_S and hit[1] <= since:
            return {d: v for d, v in hit[2].items() if d >= since}
        start = min(since, hit[1]) if hit else since
        try:
            values = _download(CODES[name], start, date.today())
            _data[name] = (time.time(), start, values)
            _failed_at.pop(name, None)
        except Exception as e:
            logger.warning(f"br_rates: {name} download failed ({type(e).__name__})")
            _failed_at[name] = time.time()
            values = hit[2] if hit else {}
    return {d: v for d, v in values.items() if d >= since}


def clear_cache() -> None:
    _data.clear()
    _failed_at.clear()
