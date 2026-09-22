from unittest.mock import MagicMock

import deezer
import pytest

from SyncZik import auth
from SyncZik.providers.deezer import DeezerProvider, _parse_artists, _parse_song


def make_artist(id=1, name="Artist") -> deezer.Artist:
    return deezer.Artist(client=MagicMock(), json={"id": id, "name": name})


def make_track(id=1, title="Track", artist=None, contributors=None, link=None) -> deezer.Track:
    artist = artist or make_artist(id=1, name="Main Artist")
    contributors = contributors if contributors is not None else []
    json = {
        "id": id,
        "title": title,
        "link": link or f"https://www.deezer.com/track/{id}",
        "artist": {"id": artist.id, "name": artist.name},
        "contributors": [{"id": a.id, "name": a.name} for a in contributors],
    }
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

    raw_playlist.add_tracks.assert_called_once_with([])


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
