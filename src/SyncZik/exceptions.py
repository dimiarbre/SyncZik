"""SyncZik-specific exceptions raised at the provider boundary.

Provider implementations translate the underlying library's raw exceptions
into one of these, so callers (sync_engine, tui) get a consistent, actionable
error regardless of which streaming service raised it.
"""

from __future__ import annotations

import deezer.exceptions
import spotipy


class SyncZikError(Exception):
    """Base class for all SyncZik-specific errors."""


class ProviderAuthError(SyncZikError):
    """The provider rejected the request due to an expired/invalid credential."""


class ProviderRateLimitError(SyncZikError):
    """The provider is rate-limiting requests and retries were exhausted."""


class ProviderNotFoundError(SyncZikError):
    """The requested playlist/track/resource doesn't exist on the provider."""


class ProviderError(SyncZikError):
    """Catch-all for any other provider-side failure."""


def translate_provider_error(exc: Exception) -> SyncZikError | None:
    """Map a raw spotipy/deezer exception to a SyncZikError, or None if unrecognized."""
    if isinstance(exc, spotipy.SpotifyException):
        if exc.http_status in (401, 403):
            return ProviderAuthError(f"Spotify authentication failed: {exc.msg}")
        if exc.http_status == 404:
            return ProviderNotFoundError(f"Spotify resource not found: {exc.msg}")
        if exc.http_status == 429:
            return ProviderRateLimitError(f"Spotify rate limit exceeded: {exc.msg}")
        return ProviderError(f"Spotify API error: {exc.msg}")

    if isinstance(exc, deezer.exceptions.DeezerForbiddenError):
        return ProviderAuthError(f"Deezer authentication failed: {exc}")
    if isinstance(exc, deezer.exceptions.DeezerNotFoundError):
        return ProviderNotFoundError(f"Deezer resource not found: {exc}")
    if isinstance(exc, deezer.exceptions.DeezerHTTPError):
        # The generic DeezerHTTPError's first positional arg is the HTTP status
        # code when the API returned a body (see DeezerHTTPError.__init__) —
        # deezer-python doesn't classify 429 on its own, so check it here.
        status = exc.args[0] if exc.args else None
        if status == 429:
            return ProviderRateLimitError(f"Deezer rate limit exceeded: {exc}")
        return ProviderError(f"Deezer API error: {exc}")
    if isinstance(exc, deezer.exceptions.DeezerAPIException):
        return ProviderError(f"Deezer API error: {exc}")

    return None
