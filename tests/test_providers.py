from unittest.mock import MagicMock

import deezer
import deezer.exceptions
import httpx
import pytest
import spotipy

from SyncZik import auth
from SyncZik.exceptions import ProviderAuthError, ProviderNotFoundError, ProviderRateLimitError
from SyncZik.providers.deezer import DeezerProvider, _parse_artists, _parse_song
from SyncZik.providers.spotify import SpotifyProvider
from SyncZik.providers.spotify import _parse_song as _parse_spotify_song
from SyncZik.syncer import Song


def _deezer_http_error(status_code: int, text: str = '{"error": "boom"}') -> deezer.exceptions.DeezerHTTPError:
    request = httpx.Request("GET", "https://api.deezer.com/x")
    response = httpx.Response(status_code, request=request, text=text)
    http_exc = httpx.HTTPStatusError("error", request=request, response=response)
    return deezer.exceptions.DeezerHTTPError.from_http_error(http_exc)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("SyncZik.retry.time.sleep", lambda seconds: None)


def make_artist(id=1, name="Artist") -> deezer.Artist:
    return deezer.Artist(client=MagicMock(), json={"id": id, "name": name})


def make_track(id=1, title="Track", artist=None, contributors=None, link=None,
                isrc=None, duration=None, album=None) -> deezer.Track:
    artist = artist or make_artist(id=1, name="Main Artist")
    contributors = contributors if contributors is not None else []
    json = {
        "id": id,
        "title": title,
        "link": link or f"https://www.deezer.com/track/{id}",
        "artist": {"id": artist.id, "name": artist.name},
        "contributors": [{"id": a.id, "name": a.name} for a in contributors],
    }
    if isrc is not None:
        json["isrc"] = isrc
    if duration is not None:
        json["duration"] = duration
    if album is not None:
        json["album"] = {"id": 1, "title": album}
    return deezer.Track(client=MagicMock(), json=json)


def make_deezer_playlist(id=1, title="Playlist", owner="Owner", tracks=None) -> deezer.Playlist:
    return deezer.Playlist(
        client=MagicMock(),
        json={
            "id": id,
            "title": title,
            "creator": {"id": 1, "name": owner},
            "tracks": [],
        },
    )


# ---------------------------------------------------------------------------
# _parse_artists / _parse_song
# ---------------------------------------------------------------------------

def test_parse_artists():
    artists = [make_artist(1, "A"), make_artist(2, "B")]
    result = _parse_artists(artists)
    assert [a.name for a in result] == ["A", "B"]
    assert [a.id for a in result] == ["1", "2"]


def test_parse_song_uses_contributors_when_present():
    contributors = [make_artist(1, "Main"), make_artist(2, "Feat")]
    track = make_track(id=10, title="Song", contributors=contributors)
    song = _parse_song(track)
    assert song.name == "Song"
    assert song.id == "10"
    assert song.uri == "https://www.deezer.com/track/10"
    assert [a.name for a in song.artists] == ["Main", "Feat"]


def test_parse_song_falls_back_to_artist_when_no_contributors():
    artist = make_artist(5, "Solo")
    track = make_track(id=11, title="Solo Song", artist=artist)
    song = _parse_song(track)
    assert [a.name for a in song.artists] == ["Solo"]


def test_parse_song_includes_metadata_when_present():
    track = make_track(id=10, title="Song", isrc="US123", duration=200, album="My Album")
    song = _parse_song(track)
    assert song.isrc == "US123"
    assert song.duration_ms == 200_000
    assert song.album == "My Album"


def test_parse_song_metadata_defaults_to_none_when_absent():
    # deezer-python's Resource raises AttributeError (not None) for a field
    # that was never in the JSON payload — this guards the getattr() defaults.
    track = make_track(id=11, title="Song")
    song = _parse_song(track)
    assert song.isrc is None
    assert song.duration_ms is None
    assert song.album is None


# ---------------------------------------------------------------------------
# DeezerProvider
# ---------------------------------------------------------------------------

def test_get_playlist_builds_playlist_with_songs():
    client = MagicMock(spec=deezer.Client)
    raw_playlist = make_deezer_playlist(id=1, title="My Playlist", owner="Alice")
    tracks = [make_track(id=1, title="A"), make_track(id=2, title="B")]
    raw_playlist.get_tracks = MagicMock(return_value=tracks)
    client.get_playlist.return_value = raw_playlist

    provider = DeezerProvider(client)
    playlist = provider.get_playlist("1")

    client.get_playlist.assert_called_once_with(1)
    assert playlist.name == "My Playlist"
    assert playlist.owner == "Alice"
    assert playlist.service == "deezer"
    assert [s.name for s in playlist.songs] == ["A", "B"]


def test_fetch_songs_returns_song_list():
    client = MagicMock(spec=deezer.Client)
    raw_playlist = make_deezer_playlist()
    tracks = [make_track(id=1, title="A"), make_track(id=2, title="B")]
    raw_playlist.get_tracks = MagicMock(return_value=tracks)
    client.get_playlist.return_value = raw_playlist

    provider = DeezerProvider(client)
    songs = provider.fetch_songs("1")

    assert [s.name for s in songs] == ["A", "B"]


def test_search_tracks_respects_limit():
    client = MagicMock(spec=deezer.Client)
    client.search.return_value = [make_track(id=i, title=f"T{i}") for i in range(5)]

    provider = DeezerProvider(client)
    songs = provider.search_tracks("query", limit=2)

    assert len(songs) == 2
    assert [s.name for s in songs] == ["T0", "T1"]


def test_create_playlist_returns_str_id_and_ignores_user_id_description():
    client = MagicMock(spec=deezer.Client)
    client.create_playlist.return_value = 42

    provider = DeezerProvider(client)
    playlist_id = provider.create_playlist("some_user", "New Playlist", description="ignored")

    client.create_playlist.assert_called_once_with("New Playlist")
    assert playlist_id == "42"
    assert isinstance(playlist_id, str)


def test_add_songs_calls_add_tracks_with_int_ids():
    client = MagicMock(spec=deezer.Client)
    raw_playlist = make_deezer_playlist()
    raw_playlist.add_tracks = MagicMock(return_value=True)
    client.get_playlist.return_value = raw_playlist

    provider = DeezerProvider(client)
    songs = [_parse_song(make_track(id=1)), _parse_song(make_track(id=2))]
    provider.add_songs("1", songs)

    raw_playlist.add_tracks.assert_called_once_with([1, 2])


def test_remove_songs_calls_delete_tracks_with_int_ids():
    client = MagicMock(spec=deezer.Client)
    raw_playlist = make_deezer_playlist()
    raw_playlist.delete_tracks = MagicMock(return_value=True)
    client.get_playlist.return_value = raw_playlist

    provider = DeezerProvider(client)
    songs = [_parse_song(make_track(id=1))]
    provider.remove_songs("1", songs)

    raw_playlist.delete_tracks.assert_called_once_with([1])


def test_add_songs_empty_list_does_not_raise():
    client = MagicMock(spec=deezer.Client)
    raw_playlist = make_deezer_playlist()
    raw_playlist.add_tracks = MagicMock(return_value=True)
    client.get_playlist.return_value = raw_playlist

    provider = DeezerProvider(client)
    provider.add_songs("1", [])

    # Batching now skips the API call entirely for an empty batch (previously
    # called add_tracks([]) unconditionally).
    raw_playlist.add_tracks.assert_not_called()


def test_add_songs_batches_over_size_limit():
    client = MagicMock(spec=deezer.Client)
    raw_playlist = make_deezer_playlist()
    raw_playlist.add_tracks = MagicMock(return_value=True)
    client.get_playlist.return_value = raw_playlist

    provider = DeezerProvider(client)
    songs = [_parse_song(make_track(id=i)) for i in range(150)]
    provider.add_songs("1", songs)

    assert raw_playlist.add_tracks.call_count == 2
    first_batch = raw_playlist.add_tracks.call_args_list[0][0][0]
    assert len(first_batch) == 100


def test_remove_songs_batches_over_size_limit():
    client = MagicMock(spec=deezer.Client)
    raw_playlist = make_deezer_playlist()
    raw_playlist.delete_tracks = MagicMock(return_value=True)
    client.get_playlist.return_value = raw_playlist

    provider = DeezerProvider(client)
    songs = [_parse_song(make_track(id=i)) for i in range(150)]
    provider.remove_songs("1", songs)

    assert raw_playlist.delete_tracks.call_count == 2


# ---------------------------------------------------------------------------
# DeezerProvider — error translation & retry
# ---------------------------------------------------------------------------

class TestDeezerProviderErrorHandling:
    def test_get_playlist_translates_404_to_not_found(self):
        client = MagicMock(spec=deezer.Client)
        client.get_playlist.side_effect = _deezer_http_error(404)
        provider = DeezerProvider(client)
        with pytest.raises(ProviderNotFoundError):
            provider.get_playlist("1")

    def test_search_tracks_translates_429_to_rate_limit(self):
        client = MagicMock(spec=deezer.Client)
        client.search.side_effect = _deezer_http_error(429)
        provider = DeezerProvider(client)
        with pytest.raises(ProviderRateLimitError):
            provider.search_tracks("query")

    def test_get_playlist_retries_transient_error_then_succeeds(self):
        client = MagicMock(spec=deezer.Client)
        raw_playlist = make_deezer_playlist(title="P", owner="U")
        raw_playlist.get_tracks = MagicMock(return_value=[])
        client.get_playlist.side_effect = [_deezer_http_error(503), raw_playlist]

        provider = DeezerProvider(client)
        playlist = provider.get_playlist("1")

        assert playlist.name == "P"
        assert client.get_playlist.call_count == 2


# ---------------------------------------------------------------------------
# get_deezer_client
# ---------------------------------------------------------------------------

def test_get_deezer_client_raises_without_token(monkeypatch):
    monkeypatch.setattr(auth, "DEEZER_ACCESS_TOKEN", None)
    monkeypatch.setattr(auth, "_deezer_client", None)

    with pytest.raises(RuntimeError, match="DEEZER_ACCESS_TOKEN"):
        auth.get_deezer_client()


def test_get_deezer_client_caches_instance(monkeypatch):
    monkeypatch.setattr(auth, "DEEZER_ACCESS_TOKEN", "fake_token")
    monkeypatch.setattr(auth, "_deezer_client", None)

    client1 = auth.get_deezer_client()
    client2 = auth.get_deezer_client()

    assert client1 is client2


# ---------------------------------------------------------------------------
# SpotifyProvider — Spotify's API returns plain dicts (no resource classes),
# so fixtures here are just nested dict/list literals shaped like its JSON.
# ---------------------------------------------------------------------------

def make_spotify_track_item(id="1", name="Track", artists=None, uri=None,
                             album=None, duration_ms=None, isrc=None, added_at=None) -> dict:
    artists = artists if artists is not None else [{"id": "a1", "name": "Artist"}]
    track = {
        "id": id,
        "name": name,
        "uri": uri or f"spotify:track:{id}",
        "artists": artists,
    }
    if album is not None:
        track["album"] = {"name": album}
    if duration_ms is not None:
        track["duration_ms"] = duration_ms
    if isrc is not None:
        track["external_ids"] = {"isrc": isrc}
    item = {"track": track}
    if added_at is not None:
        item["added_at"] = added_at
    return item


def make_song(id="s1") -> Song:
    return Song(name=id, artists=[], uri=f"spotify:track:{id}", id=id)


class TestSpotifyParseSong:
    def test_parses_basic_and_metadata_fields(self):
        item = make_spotify_track_item(
            id="1", name="Song", album="Album", duration_ms=200_000, isrc="US123", added_at="2024-01-01",
        )
        song = _parse_spotify_song(item)
        assert song.name == "Song"
        assert song.id == "1"
        assert song.album == "Album"
        assert song.duration_ms == 200_000
        assert song.isrc == "US123"
        assert song.added_at == "2024-01-01"

    def test_missing_optional_fields_default_to_none(self):
        item = make_spotify_track_item(id="1", name="Song")
        song = _parse_spotify_song(item)
        assert song.album is None
        assert song.duration_ms is None
        assert song.isrc is None
        assert song.added_at is None


class TestSpotifyProvider:
    def test_get_playlist_builds_playlist_with_songs(self):
        sp = MagicMock(spec=spotipy.Spotify)
        sp.playlist.return_value = {
            "name": "My Playlist",
            "owner": {"display_name": "Alice"},
            "tracks": {
                "items": [make_spotify_track_item(id="1", name="A"), make_spotify_track_item(id="2", name="B")],
                "next": None,
            },
        }
        provider = SpotifyProvider(sp)
        playlist = provider.get_playlist("pl1")

        sp.playlist.assert_called_once_with("pl1")
        assert playlist.name == "My Playlist"
        assert playlist.owner == "Alice"
        assert playlist.service == "spotify"
        assert [s.name for s in playlist.songs] == ["A", "B"]

    def test_get_playlist_paginates(self):
        sp = MagicMock(spec=spotipy.Spotify)
        page1 = {"items": [make_spotify_track_item(id="1", name="A")], "next": "url"}
        page2 = {"items": [make_spotify_track_item(id="2", name="B")], "next": None}
        sp.playlist.return_value = {"name": "P", "owner": {"display_name": "U"}, "tracks": page1}
        sp.next.side_effect = [page2]

        provider = SpotifyProvider(sp)
        playlist = provider.get_playlist("pl1")

        assert [s.name for s in playlist.songs] == ["A", "B"]
        sp.next.assert_called_once_with(page1)

    def test_get_playlist_skips_null_tracks(self):
        sp = MagicMock(spec=spotipy.Spotify)
        sp.playlist.return_value = {
            "name": "P", "owner": {"display_name": "U"},
            "tracks": {"items": [{"track": None}, make_spotify_track_item(id="1", name="A")], "next": None},
        }
        provider = SpotifyProvider(sp)
        playlist = provider.get_playlist("pl1")
        assert [s.name for s in playlist.songs] == ["A"]

    def test_fetch_songs_returns_song_list(self):
        sp = MagicMock(spec=spotipy.Spotify)
        sp.playlist_tracks.return_value = {
            "items": [make_spotify_track_item(id="1", name="A")],
            "next": None,
        }
        provider = SpotifyProvider(sp)
        songs = provider.fetch_songs("pl1")
        assert [s.name for s in songs] == ["A"]

    def test_fetch_songs_paginates(self):
        sp = MagicMock(spec=spotipy.Spotify)
        page1 = {"items": [make_spotify_track_item(id="1", name="A")], "next": "url"}
        page2 = {"items": [make_spotify_track_item(id="2", name="B")], "next": None}
        sp.playlist_tracks.return_value = page1
        sp.next.side_effect = [page2]
        provider = SpotifyProvider(sp)
        songs = provider.fetch_songs("pl1")
        assert [s.name for s in songs] == ["A", "B"]

    def test_search_tracks_passes_query_and_limit(self):
        sp = MagicMock(spec=spotipy.Spotify)
        sp.search.return_value = {"tracks": {"items": [
            {"id": "1", "name": "T1", "uri": "u1", "artists": [{"id": "a", "name": "A"}]},
        ]}}
        provider = SpotifyProvider(sp)
        songs = provider.search_tracks("query", limit=1)
        sp.search.assert_called_once_with(q="query", type="track", limit=1)
        assert [s.name for s in songs] == ["T1"]

    def test_create_playlist_returns_id(self):
        sp = MagicMock(spec=spotipy.Spotify)
        sp.user_playlist_create.return_value = {"id": "new123"}
        provider = SpotifyProvider(sp)
        playlist_id = provider.create_playlist("user", "New", description="desc")
        sp.user_playlist_create.assert_called_once_with(user="user", name="New", public=True, description="desc")
        assert playlist_id == "new123"

    def test_add_songs_batches_over_size_limit(self):
        sp = MagicMock(spec=spotipy.Spotify)
        provider = SpotifyProvider(sp)
        songs = [make_song(f"s{i}") for i in range(150)]
        provider.add_songs("pl1", songs)
        assert sp.playlist_add_items.call_count == 2
        first_batch = sp.playlist_add_items.call_args_list[0][0][1]
        assert len(first_batch) == 100

    def test_add_songs_empty_list_skips_call(self):
        sp = MagicMock(spec=spotipy.Spotify)
        provider = SpotifyProvider(sp)
        provider.add_songs("pl1", [])
        sp.playlist_add_items.assert_not_called()

    def test_remove_songs_calls_remove_all_occurrences(self):
        sp = MagicMock(spec=spotipy.Spotify)
        provider = SpotifyProvider(sp)
        provider.remove_songs("pl1", [make_song("s1")])
        sp.playlist_remove_all_occurrences_of_items.assert_called_once_with("pl1", ["spotify:track:s1"])


class TestSpotifyProviderErrorHandling:
    def test_get_playlist_translates_404_to_not_found(self):
        sp = MagicMock(spec=spotipy.Spotify)
        sp.playlist.side_effect = spotipy.SpotifyException(404, -1, "not found")
        provider = SpotifyProvider(sp)
        with pytest.raises(ProviderNotFoundError):
            provider.get_playlist("missing")

    def test_search_tracks_retries_429_then_succeeds(self):
        sp = MagicMock(spec=spotipy.Spotify)
        sp.search.side_effect = [
            spotipy.SpotifyException(429, -1, "rate limited", headers={"Retry-After": "0"}),
            {"tracks": {"items": []}},
        ]
        provider = SpotifyProvider(sp)
        songs = provider.search_tracks("q")
        assert songs == []
        assert sp.search.call_count == 2

    def test_create_playlist_translates_403_to_auth_error(self):
        sp = MagicMock(spec=spotipy.Spotify)
        sp.user_playlist_create.side_effect = spotipy.SpotifyException(403, -1, "forbidden")
        provider = SpotifyProvider(sp)
        with pytest.raises(ProviderAuthError):
            provider.create_playlist("user", "name")
