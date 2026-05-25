"""Backward-compatible re-export. Prefer importing from providers.spotify directly."""
from providers.spotify import SpotifyProvider

__all__ = ["SpotifyProvider"]
