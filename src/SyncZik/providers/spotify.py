import spotipy

from providers.base import ServiceProvider
from syncer import Artist, Playlist, Song
from utils import ServiceName

_BATCH_SIZE = 100


def _parse_artists(artists_json: list) -> list[Artist]:
    return [Artist(name=a["name"], id=a["id"]) for a in artists_json]


def _parse_song(item: dict) -> Song:
    track = item["track"]
    return Song(
        name=track["name"],
        artists=_parse_artists(track["artists"]),
        uri=track["uri"],
        id=track["id"],
    )


class SpotifyProvider(ServiceProvider):
    def __init__(self, sp: spotipy.Spotify):
        self._sp = sp

    @property
    def service_name(self) -> ServiceName:
        return "spotify"

    def get_playlist(self, playlist_id: str) -> Playlist:
        raw = self._sp.playlist(playlist_id)
        playlist = Playlist(
            service="spotify",
            service_id=playlist_id,
            name=raw["name"],
            owner=raw["owner"]["display_name"],
        )
        tracks = raw["tracks"]
        while tracks:
            for item in tracks["items"]:
                if item["track"] is None:
                    continue
                playlist.add_song(_parse_song(item), allow_duplicate=False)
            tracks = self._sp.next(tracks) if tracks["next"] else None
        return playlist

    def fetch_songs(self, playlist_id: str) -> list[Song]:
        songs: list[Song] = []
        tracks = self._sp.playlist_tracks(playlist_id)
        while tracks:
            for item in tracks["items"]:
                if item["track"] is None:
                    continue
                songs.append(_parse_song(item))
            tracks = self._sp.next(tracks) if tracks["next"] else None
        return songs

    def search_tracks(self, query: str, limit: int = 10) -> list[Song]:
        results = self._sp.search(q=query, type="track", limit=limit)
        return [
            Song(
                name=item["name"],
                artists=_parse_artists(item["artists"]),
                uri=item["uri"],
                id=item["id"],
            )
            for item in results["tracks"]["items"]
        ]

    def create_playlist(self, user_id: str, name: str, description: str = "") -> str:
        result = self._sp.user_playlist_create(
            user=user_id,
            name=name,
            public=True,
            description=description,
        )
        return result["id"]

    def add_songs(self, playlist_id: str, songs: list[Song]) -> None:
        uris = [s.uri for s in songs]
        for i in range(0, len(uris), _BATCH_SIZE):
            self._sp.playlist_add_items(playlist_id, uris[i:i + _BATCH_SIZE])

    def remove_songs(self, playlist_id: str, songs: list[Song]) -> None:
        uris = [s.uri for s in songs]
        for i in range(0, len(uris), _BATCH_SIZE):
            self._sp.playlist_remove_all_occurrences_of_items(playlist_id, uris[i:i + _BATCH_SIZE])
