from abc import ABC, abstractmethod

from syncer import Playlist, Song
from utils import ServiceName


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
