from providers.base import ServiceProvider
from syncer import Playlist, Song
from utils import ServiceName


class DeezerProvider(ServiceProvider):
    """Deezer adapter — not yet implemented."""

    def __init__(self):
        raise NotImplementedError("Deezer support is planned for a future release.")

    @property
    def service_name(self) -> ServiceName:
        return "deezer"

    def get_playlist(self, playlist_id: str) -> Playlist:
        raise NotImplementedError

    def fetch_songs(self, playlist_id: str) -> list[Song]:
        raise NotImplementedError

    def search_tracks(self, query: str, limit: int = 10) -> list[Song]:
        raise NotImplementedError

    def create_playlist(self, user_id: str, name: str, description: str = "") -> str:
        raise NotImplementedError

    def add_songs(self, playlist_id: str, songs: list[Song]) -> None:
        raise NotImplementedError

    def remove_songs(self, playlist_id: str, songs: list[Song]) -> None:
        raise NotImplementedError
