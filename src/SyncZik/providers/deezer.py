import deezer

from ..syncer import Artist, Playlist, Song
from ..utils import ServiceName
from .base import ServiceProvider, resilient_call

# Deezer's playlist add/delete-tracks endpoints don't document an explicit
# batch-size limit; chunk anyway (same size as Spotify's documented one) as a
# conservative safety margin against very large playlists.
_BATCH_SIZE = 100


def _parse_artists(artists: list[deezer.Artist]) -> list[Artist]:
    return [Artist(name=a.name, id=str(a.id)) for a in artists]


def _parse_song(track: deezer.Track) -> Song:
    # deezer-python parses `contributors` into Artist objects but leaves the
    # single `artist` field as a raw dict (no `_parse_artist` in the library),
    # so the two need different handling when contributors is empty. `album`
    # is likewise left as a raw dict (no `_parse_album`). Any of isrc/duration/
    # album/contributors can simply be absent from the API response, and
    # deezer-python's Resource raises AttributeError (not None) for a field
    # that was never set — hence the getattr() defaults throughout.
    if track.contributors:
        artists = _parse_artists(track.contributors)
    else:
        artists = [Artist(name=track.artist["name"], id=str(track.artist["id"]))]

    album = getattr(track, "album", None)
    duration = getattr(track, "duration", None)

    return Song(
        name=track.title,
        artists=artists,
        uri=track.link,
        id=str(track.id),
        album=album.get("title") if isinstance(album, dict) else None,
        duration_ms=duration * 1000 if duration is not None else None,
        isrc=getattr(track, "isrc", None),
    )


class DeezerProvider(ServiceProvider):
    def __init__(self, client: deezer.Client):
        self._client = client

    @property
    def service_name(self) -> ServiceName:
        return "deezer"

    def get_playlist(self, playlist_id: str) -> Playlist:
        raw = resilient_call(lambda: self._client.get_playlist(int(playlist_id)))
        # `creator` is left as a raw dict by deezer-python (no `_parse_creator`
        # on the Playlist resource), unlike `contributors` on Track.
        playlist = Playlist(
            service="deezer",
            service_id=playlist_id,
            name=raw.title,
            owner=raw.creator["name"],
        )
        # Force full pagination inside the retried call: get_tracks() returns a
        # lazily-paginated list, so a transient failure part-way through a page
        # would otherwise escape resilient_call's retry/translate wrapping.
        for track in resilient_call(lambda: list(raw.get_tracks())):
            playlist.add_song(_parse_song(track), allow_duplicate=False)
        return playlist

    def fetch_songs(self, playlist_id: str) -> list[Song]:
        raw = resilient_call(lambda: self._client.get_playlist(int(playlist_id)))
        tracks = resilient_call(lambda: list(raw.get_tracks()))
        return [_parse_song(t) for t in tracks]

    def search_tracks(self, query: str, limit: int = 10) -> list[Song]:
        results = resilient_call(lambda: self._client.search(query=query))
        tracks = resilient_call(lambda: list(results[:limit]))
        return [_parse_song(t) for t in tracks]

    def create_playlist(self, user_id: str, name: str, description: str = "") -> str:
        # Deezer's create-playlist endpoint always acts on the token's own
        # account and has no description field — user_id/description are kept
        # for ServiceProvider interface parity but unused here.
        playlist_id = resilient_call(lambda: self._client.create_playlist(name))
        return str(playlist_id)

    def add_songs(self, playlist_id: str, songs: list[Song]) -> None:
        playlist = resilient_call(lambda: self._client.get_playlist(int(playlist_id)))
        ids = [int(s.id) for s in songs]
        for i in range(0, len(ids), _BATCH_SIZE):
            batch = ids[i : i + _BATCH_SIZE]
            resilient_call(lambda: playlist.add_tracks(batch))

    def remove_songs(self, playlist_id: str, songs: list[Song]) -> None:
        playlist = resilient_call(lambda: self._client.get_playlist(int(playlist_id)))
        ids = [int(s.id) for s in songs]
        for i in range(0, len(ids), _BATCH_SIZE):
            batch = ids[i : i + _BATCH_SIZE]
            resilient_call(lambda: playlist.delete_tracks(batch))
