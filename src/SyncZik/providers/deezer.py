import deezer

from .base import ServiceProvider
from ..syncer import Artist, Playlist, Song
from ..utils import ServiceName


def _parse_artists(artists: list[deezer.Artist]) -> list[Artist]:
    return [Artist(name=a.name, id=str(a.id)) for a in artists]


def _parse_song(track: deezer.Track) -> Song:
    # deezer-python parses `contributors` into Artist objects but leaves the
    # single `artist` field as a raw dict (no `_parse_artist` in the library),
    # so the two need different handling when contributors is empty.
    if track.contributors:
        artists = _parse_artists(track.contributors)
    else:
        artists = [Artist(name=track.artist["name"], id=str(track.artist["id"]))]
    return Song(
        name=track.title,
        artists=artists,
        uri=track.link,
        id=str(track.id),
    )


class DeezerProvider(ServiceProvider):
    def __init__(self, client: deezer.Client):
        self._client = client

    @property
    def service_name(self) -> ServiceName:
        return "deezer"

    def get_playlist(self, playlist_id: str) -> Playlist:
        raw = self._client.get_playlist(int(playlist_id))
        # `creator` is left as a raw dict by deezer-python (no `_parse_creator`
        # on the Playlist resource), unlike `contributors` on Track.
        playlist = Playlist(
            service="deezer",
            service_id=playlist_id,
            name=raw.title,
            owner=raw.creator["name"],
        )
        for track in raw.get_tracks():
            playlist.add_song(_parse_song(track), allow_duplicate=False)
        return playlist

    def fetch_songs(self, playlist_id: str) -> list[Song]:
        raw = self._client.get_playlist(int(playlist_id))
        return [_parse_song(t) for t in raw.get_tracks()]

    def search_tracks(self, query: str, limit: int = 10) -> list[Song]:
        results = self._client.search(query=query)
        return [_parse_song(t) for t in results[:limit]]

    def create_playlist(self, user_id: str, name: str, description: str = "") -> str:
        # Deezer's create-playlist endpoint always acts on the token's own
        # account and has no description field — user_id/description are kept
        # for ServiceProvider interface parity but unused here.
        playlist_id = self._client.create_playlist(name)
        return str(playlist_id)

    def add_songs(self, playlist_id: str, songs: list[Song]) -> None:
        playlist = self._client.get_playlist(int(playlist_id))
        playlist.add_tracks([int(s.id) for s in songs])

    def remove_songs(self, playlist_id: str, songs: list[Song]) -> None:
        playlist = self._client.get_playlist(int(playlist_id))
        playlist.delete_tracks([int(s.id) for s in songs])
