from pathlib import Path
from unittest.mock import MagicMock

import pytest
from SyncZik.syncer import Artist, Song, Playlist
from SyncZik.providers.base import ServiceProvider
from SyncZik.playlist_git import (
    LogEntry,
    PlaylistDiff,
    cherry_pick,
    diff,
    fork_from_user,
    log,
    revert,
    songs_in_playlist,
)
import SyncZik.snapshot_handler as sh


def make_song(name="Track", id="s1") -> Song:
    return Song(name=name, artists=[Artist("Artist", "a1")], uri=f"spotify:track:{id}", id=id)


def make_playlist(service_id="pl1", songs=None) -> Playlist:
    p = Playlist(service="spotify", service_id=service_id, name="Test", owner="user")
    for s in (songs or []):
        p.add_song(s)
    return p


def make_provider(songs: list[Song], new_id: str = "new_pl") -> ServiceProvider:
    provider = MagicMock(spec=ServiceProvider)
    provider.service_name = "spotify"
    provider.fetch_songs.return_value = list(songs)
    provider.get_playlist.return_value = make_playlist(songs=songs)
    provider.create_playlist.return_value = new_id
    return provider


@pytest.fixture(autouse=True)
def tmp_workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


# ---------------------------------------------------------------------------
# diff()
# ---------------------------------------------------------------------------

class TestDiff:
    def test_identical_playlists(self):
        songs = [make_song("A", "a"), make_song("B", "b")]
        left = make_playlist(songs=songs)
        right = make_playlist(service_id="pl2", songs=songs)
        d = diff(left, right)
        assert d.is_identical()
        assert len(d.in_both) == 2

    def test_disjoint_playlists(self):
        a, b = make_song("A", "a"), make_song("B", "b")
        left = make_playlist(songs=[a])
        right = make_playlist(service_id="pl2", songs=[b])
        d = diff(left, right)
        assert not d.is_identical()
        assert d.only_in_left == [a]
        assert d.only_in_right == [b]
        assert d.in_both == []

    def test_partial_overlap(self):
        a, b, c = make_song("A", "a"), make_song("B", "b"), make_song("C", "c")
        left = make_playlist(songs=[a, b])
        right = make_playlist(service_id="pl2", songs=[b, c])
        d = diff(left, right)
        assert {s.id for s in d.only_in_left} == {"a"}
        assert {s.id for s in d.only_in_right} == {"c"}
        assert {s.id for s in d.in_both} == {"b"}

    def test_empty_vs_non_empty(self):
        a = make_song("A", "a")
        left = make_playlist(songs=[])
        right = make_playlist(service_id="pl2", songs=[a])
        d = diff(left, right)
        assert d.only_in_right == [a]
        assert d.only_in_left == []

    def test_both_empty(self):
        d = diff(make_playlist(songs=[]), make_playlist(service_id="pl2", songs=[]))
        assert d.is_identical()
        assert d.in_both == []

    def test_diff_is_not_symmetric_in_position_but_correct_by_id(self):
        a, b, c = make_song("A", "a"), make_song("B", "b"), make_song("C", "c")
        left = make_playlist(songs=[a, b, c])
        right = make_playlist(service_id="pl2", songs=[c, b, a])
        d = diff(left, right)
        assert d.is_identical()
        assert len(d.in_both) == 3


# ---------------------------------------------------------------------------
# cherry_pick()
# ---------------------------------------------------------------------------

class TestCherryPick:
    def test_adds_new_songs(self):
        target = make_playlist(songs=[make_song("A", "a")])
        b, c = make_song("B", "b"), make_song("C", "c")
        added = cherry_pick(target, [b, c])
        assert len(added) == 2
        assert b in target.songs
        assert c in target.songs

    def test_skips_existing_songs(self):
        a = make_song("A", "a")
        target = make_playlist(songs=[a])
        added = cherry_pick(target, [a])
        assert added == []
        assert len(target.songs) == 1

    def test_partial_skip(self):
        a, b = make_song("A", "a"), make_song("B", "b")
        target = make_playlist(songs=[a])
        added = cherry_pick(target, [a, b])
        assert len(added) == 1
        assert added[0].id == "b"

    def test_empty_pick_list(self):
        target = make_playlist(songs=[make_song("A", "a")])
        added = cherry_pick(target, [])
        assert added == []
        assert len(target.songs) == 1

    def test_persists_state_after_pick(self):
        target = make_playlist(songs=[])
        cherry_pick(target, [make_song("A", "a")])
        assert Path("state/spotify/pl1.json").exists()

    def test_no_persistence_when_nothing_added(self):
        a = make_song("A", "a")
        target = make_playlist(songs=[a])
        cherry_pick(target, [a])
        assert not Path("state/spotify/pl1.json").exists()

    def test_pick_from_diff_result(self):
        a, b, c = make_song("A", "a"), make_song("B", "b"), make_song("C", "c")
        source = make_playlist(service_id="source", songs=[a, b, c])
        target = make_playlist(songs=[a])
        d = diff(target, source)
        added = cherry_pick(target, d.only_in_right)
        assert {s.id for s in added} == {"b", "c"}
        assert len(target.songs) == 3


# ---------------------------------------------------------------------------
# fork_from_user()
# ---------------------------------------------------------------------------

class TestForkFromUser:
    def test_creates_new_playlist_on_remote(self):
        songs = [make_song("A", "a"), make_song("B", "b")]
        provider = make_provider(songs, new_id="forked123")
        p = fork_from_user(provider, "user", "source_pl", "My Fork")
        provider.create_playlist.assert_called_once_with("user", "My Fork", "")
        assert p.service_id == "forked123"
        assert p.parent_id == "source_pl"

    def test_saves_state_and_snapshot(self):
        songs = [make_song("A", "a")]
        provider = make_provider(songs, new_id="forked123")
        fork_from_user(provider, "user", "source_pl", "My Fork")
        assert Path("state/spotify/forked123.json").exists()
        assert list(Path("snapshots/spotify/forked123").glob("*.json"))

    def test_fork_includes_custom_description(self):
        songs = [make_song("A", "a")]
        provider = make_provider(songs, new_id="forked123")
        fork_from_user(provider, "user", "source_pl", "My Fork", description="Custom desc")
        provider.create_playlist.assert_called_once_with("user", "My Fork", "Custom desc")


# ---------------------------------------------------------------------------
# songs_in_playlist()
# ---------------------------------------------------------------------------

class TestSongsInPlaylist:
    def test_fetches_remote_songs(self):
        songs = [make_song("A", "a"), make_song("B", "b")]
        provider = make_provider(songs)
        result = songs_in_playlist(provider, "any_playlist_id")
        provider.fetch_songs.assert_called_once_with("any_playlist_id")
        assert len(result) == 2

    def test_returns_empty_for_empty_playlist(self):
        provider = make_provider([])
        result = songs_in_playlist(provider, "empty")
        assert result == []


# ---------------------------------------------------------------------------
# log() — derived from the versioned snapshot history
# ---------------------------------------------------------------------------

class TestLog:
    def test_empty_when_nothing_recorded(self):
        assert log("spotify", "pl1") == []

    def test_single_version_reports_all_songs_as_added(self):
        a, b = make_song("A", "a"), make_song("B", "b")
        sh.save_snapshot("spotify", "pl1", [a, b])
        entries = log("spotify", "pl1")
        assert len(entries) == 1
        assert {s.id for s in entries[0].added} == {"a", "b"}
        assert entries[0].removed == []
        assert entries[0].total_songs == 2

    def test_reports_added_and_removed_between_versions(self):
        a, b, c = make_song("A", "a"), make_song("B", "b"), make_song("C", "c")
        sh.save_snapshot("spotify", "pl1", [a, b])
        sh.save_snapshot("spotify", "pl1", [a, c])  # b removed, c added
        entries = log("spotify", "pl1")
        assert len(entries) == 2
        newest = entries[0]
        assert {s.id for s in newest.added} == {"c"}
        assert {s.id for s in newest.removed} == {"b"}
        assert newest.total_songs == 2

    def test_newest_first(self):
        sh.save_snapshot("spotify", "pl1", [make_song("A", "a")])
        sh.save_snapshot("spotify", "pl1", [make_song("A", "a"), make_song("B", "b")])
        entries = log("spotify", "pl1")
        assert entries[0].timestamp > entries[1].timestamp


# ---------------------------------------------------------------------------
# revert() — local-only restore to a past snapshot version
# ---------------------------------------------------------------------------

class TestRevert:
    def test_restores_local_songs_to_past_version(self):
        a, b = make_song("A", "a"), make_song("B", "b")
        sh.save_snapshot("spotify", "pl1", [a])
        old_versions = sh.list_snapshot_versions("spotify", "pl1")
        sh.save_snapshot("spotify", "pl1", [a, b])

        playlist = make_playlist(songs=[a, b])
        result = revert(playlist, old_versions[0].timestamp)

        assert {s.id for s in result.songs} == {"a"}
        assert result is playlist

    def test_persists_reverted_state(self):
        a = make_song("A", "a")
        sh.save_snapshot("spotify", "pl1", [a])
        [version] = sh.list_snapshot_versions("spotify", "pl1")
        playlist = make_playlist(songs=[a, make_song("B", "b")])

        revert(playlist, version.timestamp)

        loaded = sh.load_playlist_state("spotify", "pl1")
        assert {s.id for s in loaded.songs} == {"a"}

    def test_raises_for_unknown_timestamp(self):
        from datetime import datetime, timezone
        playlist = make_playlist(songs=[make_song()])
        with pytest.raises(ValueError):
            revert(playlist, datetime(2000, 1, 1, tzinfo=timezone.utc))
