"""Retry helper for transient provider API failures (rate limits, timeouts, 5xx).

Spotify calls already get transport-level retries from spotipy/urllib3 for
GET/POST/PUT/DELETE on 429/5xx (see spotipy.client.Spotify._build_session).
This is a second, provider-agnostic layer that also covers Deezer — whose
client (deezer-python) has no retry logic of its own — and any residual
failures after Spotify's own retries are exhausted.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable

import deezer.exceptions
import httpx
import spotipy

_TRANSIENT_HTTP_STATUSES = {429, 500, 502, 503, 504}
_TRANSIENT_NETWORK_ERRORS = (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError)


def _retry_delay(exc: Exception, attempt: int, base_delay: float) -> float | None:
    """Seconds to wait before retrying `exc`, or None if it isn't transient."""
    if isinstance(exc, spotipy.SpotifyException):
        if exc.http_status not in _TRANSIENT_HTTP_STATUSES:
            return None
        retry_after = (exc.headers or {}).get("Retry-After")
        if retry_after is not None:
            try:
                return float(retry_after)
            except ValueError:
                pass
    elif isinstance(exc, deezer.exceptions.DeezerRetryableException):
        pass
    elif isinstance(exc, deezer.exceptions.DeezerHTTPError):
        status = exc.args[0] if exc.args else None
        if status not in _TRANSIENT_HTTP_STATUSES:
            return None
    elif isinstance(exc, _TRANSIENT_NETWORK_ERRORS):
        pass
    else:
        return None

    delay = base_delay * (2 ** (attempt - 1))
    return delay + random.uniform(0, delay * 0.1)


def with_retry[T](fn: Callable[[], T], *, max_attempts: int = 3, base_delay: float = 1.0) -> T:
    """Call fn(), retrying on transient provider errors with exponential backoff + jitter."""
    attempt = 0
    while True:
        attempt += 1
        try:
            return fn()
        except Exception as exc:
            delay = _retry_delay(exc, attempt, base_delay)
            if delay is None or attempt >= max_attempts:
                raise
            time.sleep(delay)
