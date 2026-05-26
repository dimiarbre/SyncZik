import json
import tempfile
from unittest.mock import MagicMock, patch
from pathlib import Path

import pytest
from SyncZik.syncer import Artist, Song, Playlist
from SyncZik.sync_engine import (
    MergeResult,
    add_song,
    apply_remote_removal,
    clone,
    remove_song,
    sync,
)
from SyncZik.providers.base import ServiceProvider
from SyncZik.utils import ServiceName


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_song(name="Track", id="id1") -> Song:
    return Song(name=name, artists=[Artist("Artist", "a1")], uri=f"spotify:track:{id}", id=id)


def make_playlist(songs: list[Song], service_id="pl1") -> Playlist:
    p = Playlist(service="spotify", service_id=service_id, name="Test", owner="user")
    for s in songs:
        p.add_song(s)
    return p


def make_provider(
    remote_songs: list[Song],
    new_playlist_id: str = "new_pl",
    service_name: ServiceName = "spotify",
) -> ServiceProvider:
    provider = MagicMock(spec=ServiceProvider)
    provider.service_name = service_name
    provider.fetch_songs.return_value = list(remote_songs)
    provider.get_playlist.return_value = make_playlist(remote_songs)
    provider.create_playlist.return_value = new_playlist_id
    return provider


# ---------------------------------------------------------------------------
# Tests run in a temp dir so file I/O doesn't pollute the repo
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def tmp_workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


# ---------------------------------------------------------------------------
# clone()
# ---------------------------------------------------------------------------

class TestClone:
    def test_creates_remote_playlist(self):
        songs = [make_song("A", "a"), make_song("B", "b")]
        provider = make_provider(songs, new_playlist_id="new123")
        result = clone(provider, "user", "source_id", "My Clone")
        provider.create_playlist.assert_called_once_with("user", "My Clone", "")
        provider.add_songs.assert_called_once()
        added = provider.add_songs.call_args[0][1]
        assert {s.id for s in added} == {"a", "b"}

    def test_returns_playlist_with_parent(self):
        songs = [make_song("A", "a")]
        provider = make_provider(songs, new_playlist_id="new123")
        p = clone(provider, "user", "source_id", "Clone")
        assert p.parent_id == "source_id"
        assert p.service_id == "new123"
        assert len(p.songs) == 1

    def test_saves_state_and_snapshot(self):
        songs = [make_song("A", "a")]
        provider = make_provider(songs, new_playlist_id="new123")
        clone(provider, "user", "source_id", "Clone")
        assert Path("state/spotify/new123.json").exists()
        assert Path("snapshots/spotify/new123.json").exists()


# ---------------------------------------------------------------------------
# sync() — merge logic
# ---------------------------------------------------------------------------

class TestSync:
    def _setup(self, baseline: list[Song], local: list[Song], remote: list[Song]):
        import SyncZik.snapshot_handler as sh
        playlist = make_playlist(local)
        sh.save_snapshot("spotify", playlist.service_id, baseline)
        sh.save_playlist_state(playlist)
        return playlist

    def test_clean_sync_no_changes(self):
        songs = [make_song("A", "a"), make_song("B", "b")]
        playlist = self._setup(baseline=songs, local=songs, remote=songs)
        provider = make_provider(songs)
        provider.fetch_songs.return_value = list(songs)
        result = sync(provider, playlist)
        assert result.is_clean()

    def test_remote_addition_pulled_to_local(self):
        a, b = make_song("A", "a"), make_song("B", "b")
        playlist = self._setup(baseline=[a], local=[a], remote=[a, b])
        provider = make_provider([a, b])
        provider.fetch_songs.side_effect = [[a, b], [a, b]]
        result = sync(provider, playlist)
        assert b in result.added_from_remote
        assert b in playlist.songs

    def test_local_addition_pushed_to_remote(self):
        a, b = make_song("A", "a"), make_song("B", "b")
        playlist = self._setup(baseline=[a], local=[a, b], remote=[a])
        provider = make_provider([a])
        provider.fetch_songs.side_effect = [[a], [a, b]]
        result = sync(provider, playlist)
        assert b in result.pushed_to_remote
        provider.add_songs.assert_called()

    def test_local_removal_pushed_to_remote(self):
        a, b = make_song("A", "a"), make_song("B", "b")
        playlist = self._setup(baseline=[a, b], local=[a], remote=[a, b])
        provider = make_provider([a, b])
        provider.fetch_songs.side_effect = [[a, b], [a]]
        result = sync(provider, playlist)
        assert b in result.removed_from_remote
        provider.remove_songs.assert_called()

    def test_remote_removal_returned_as_pending(self):
        a, b = make_song("A", "a"), make_song("B", "b")
        playlist = self._setup(baseline=[a, b], local=[a, b], remote=[a])
        provider = make_provider([a])
        provider.fetch_songs.side_effect = [[a], [a]]
        result = sync(provider, playlist)
        assert b in result.removed_from_remote_pending

    def test_local_removal_wins_over_remote_presence(self):
        # baseline=[a,b,c], local removed c, remote still has c + added d
        # → c should be removed from remote (local wins), d pulled into local
        a, b, c, d = (make_song(x, x) for x in "abcd")
        playlist = make_playlist([a, b])  # c was removed locally
        import SyncZik.snapshot_handler as sh
        sh.save_snapshot("spotify", playlist.service_id, [a, b, c])
        sh.save_playlist_state(playlist)
        provider = make_provider([a, b, c, d])
        provider.fetch_songs.side_effect = [[a, b, c, d], [a, b, d]]
        result = sync(provider, playlist)
        assert c in result.removed_from_remote
        assert d in result.added_from_remote
        provider.remove_songs.assert_called()

    def test_both_sides_removed_same_song_no_double_action(self):
        # baseline=[a,b], remote removed b, local also removed b
        # → b not in pending (already gone locally), no remove call needed
        a, b = make_song("A", "a"), make_song("B", "b")
        playlist = make_playlist([a])  # b removed locally
        import SyncZik.snapshot_handler as sh
        sh.save_snapshot("spotify", playlist.service_id, [a, b])
        sh.save_playlist_state(playlist)
        provider = make_provider([a])  # b also removed remotely
        provider.fetch_songs.side_effect = [[a], [a]]
        result = sync(provider, playlist)
        assert b not in result.removed_from_remote_pending
        assert b not in result.removed_from_remote


# ---------------------------------------------------------------------------
# add_song / remove_song (staging)
# ---------------------------------------------------------------------------

class TestStaging:
    def test_add_song_persists(self, tmp_path):
        p = make_playlist([make_song("A", "a")])
        b = make_song("B", "b")
        result = add_song(p, b)
        assert result is True
        assert b in p.songs
        assert Path("state/spotify/pl1.json").exists()

    def test_add_song_no_duplicate(self):
        a = make_song("A", "a")
        p = make_playlist([a])
        assert add_song(p, a) is False

    def test_remove_song_persists(self):
        a = make_song("A", "a")
        p = make_playlist([a])
        result = remove_song(p, a)
        assert result is True
        assert a not in p.songs

    def test_remove_song_not_found(self):
        p = make_playlist([])
        assert remove_song(p, make_song()) is False


# ---------------------------------------------------------------------------
# apply_remote_removal
# ---------------------------------------------------------------------------

class TestApplyRemoteRemoval:
    def test_removes_songs_from_local(self):
        a, b = make_song("A", "a"), make_song("B", "b")
        p = make_playlist([a, b])
        provider = make_provider([a])
        apply_remote_removal(provider, p, [b])
        assert b not in p.songs
        assert a in p.songs
