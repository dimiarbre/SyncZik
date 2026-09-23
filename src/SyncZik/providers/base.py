from abc import ABC, abstractmethod
from typing import Callable, TypeVar

from ..exceptions import translate_provider_error
from ..retry import with_retry
from ..syncer import Playlist, Song
from ..utils import ServiceName

T = TypeVar("T")


class ServiceProvider(ABC):
    """Unified interface every streaming service adapter must implement."""

    @property
    @abstractmethod
    def service_name(self) -> ServiceName: ...

    @abstractmethod
    def get_playlist(self, playlist_id: str) -> Playlist:
        """Fetch a playlist and all its songs from the service."""
        ...

    @abstractmethod
    def fetch_songs(self, playlist_id: str) -> list[Song]:
        """Fetch the live song list of a playlist (no metadata)."""
        ...

    @abstractmethod
    def search_tracks(self, query: str, limit: int = 10) -> list[Song]:
        """Search for tracks by name / artist."""
        ...

    @abstractmethod
    def create_playlist(self, user_id: str, name: str, description: str = "") -> str:
        """Create a new playlist. Returns the new playlist ID."""
        ...

    @abstractmethod
    def add_songs(self, playlist_id: str, songs: list[Song]) -> None:
        """Add songs to an existing playlist."""
        ...

    @abstractmethod
    def remove_songs(self, playlist_id: str, songs: list[Song]) -> None:
        """Remove songs from an existing playlist."""
        ...


def resilient_call(fn: Callable[[], T], *, max_attempts: int = 3, base_delay: float = 1.0) -> T:
    """Retry a provider API call on transient failure, then translate any error.

    Shared by SpotifyProvider/DeezerProvider so every outbound call gets the
    same retry/backoff behavior and raises a SyncZikError instead of a raw
    spotipy/deezer exception.
    """
    try:
        return with_retry(fn, max_attempts=max_attempts, base_delay=base_delay)
    except Exception as exc:
        wrapped = translate_provider_error(exc)
        if wrapped is not None:
            raise wrapped from exc
        raise
