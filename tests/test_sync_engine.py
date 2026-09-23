from unittest.mock import MagicMock

import pytest

import SyncZik.snapshot_handler as sh
from SyncZik.providers.base import ServiceProvider
from SyncZik.sync_engine import (
    MergeResult,
    add_song,
    apply_remote_removal,
    clone,
    remove_song,
    rename_playlist,
    sync,
    untrack_playlist,
)
from SyncZik.syncer import Artist, Playlist, Song
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
    monkeypatch.setenv("SYNCZIK_DATA_DIR", str(tmp_path / "xdg_data"))


# ---------------------------------------------------------------------------
# clone()
# ---------------------------------------------------------------------------


class TestClone:
    def test_creates_remote_playlist(self):
        songs = [make_song("A", "a"), make_song("B", "b")]
        provider = make_provider(songs, new_playlist_id="new123")
        clone(provider, "user", "source_id", "My Clone")
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
        assert (sh._data_dir() / "state/spotify/new123.json").exists()
        assert list((sh._data_dir() / "snapshots/spotify/new123").glob("*.json"))


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
        assert (sh._data_dir() / "state/spotify/pl1.json").exists()

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

    def test_empty_list_is_noop(self):
        a = make_song("A", "a")
        p = make_playlist([a])
        provider = make_provider([a])
        apply_remote_removal(provider, p, [])
        assert a in p.songs

    def test_persists_state_after_removal(self):
        a, b = make_song("A", "a"), make_song("B", "b")
        p = make_playlist([a, b])
        provider = make_provider([a])
        apply_remote_removal(provider, p, [b])
        assert (sh._data_dir() / "state/spotify/pl1.json").exists()


# ---------------------------------------------------------------------------
# sync() — additional edge cases
# ---------------------------------------------------------------------------


class TestSyncEdgeCases:
    def _setup(self, baseline, local, remote):
        import SyncZik.snapshot_handler as sh

        playlist = make_playlist(local)
        sh.save_snapshot("spotify", playlist.service_id, baseline)
        sh.save_playlist_state(playlist)
        return playlist

    def test_empty_playlist_sync_is_clean(self):
        playlist = self._setup(baseline=[], local=[], remote=[])
        provider = make_provider([])
        provider.fetch_songs.return_value = []
        result = sync(provider, playlist)
        assert result.is_clean()

    def test_conflict_local_added_remote_also_added_same_song(self):
        # Both sides added the same new song independently → no double-add
        a, b = make_song("A", "a"), make_song("B", "b")
        playlist = self._setup(baseline=[a], local=[a, b], remote=[a, b])
        provider = make_provider([a, b])
        provider.fetch_songs.side_effect = [[a, b], [a, b]]
        result = sync(provider, playlist)
        # b was added on both sides since baseline → not pushed (already there), not pulled (already local)
        assert b not in result.pushed_to_remote
        assert b not in result.added_from_remote

    def test_many_songs_all_pulled(self):
        a = make_song("A", "a")
        new_songs = [make_song(str(i), str(i)) for i in range(20)]
        playlist = self._setup(baseline=[a], local=[a], remote=[a] + new_songs)
        provider = make_provider([a] + new_songs)
        provider.fetch_songs.side_effect = [[a] + new_songs, [a] + new_songs]
        result = sync(provider, playlist)
        assert len(result.added_from_remote) == 20

    def test_sync_after_empty_baseline_pulls_everything(self):
        # Simulates first sync after load: baseline is empty, remote has songs
        songs = [make_song("A", "a"), make_song("B", "b")]
        playlist = self._setup(baseline=[], local=[], remote=songs)
        provider = make_provider(songs)
        provider.fetch_songs.side_effect = [songs, songs]
        result = sync(provider, playlist)
        assert len(result.added_from_remote) == 2

    def test_merge_result_is_clean_only_when_all_lists_empty(self):
        r = MergeResult()
        assert r.is_clean()
        r.added_from_remote.append(make_song())
        assert not r.is_clean()

    def test_clone_empty_source(self):
        provider = make_provider([], new_playlist_id="empty_clone")
        p = clone(provider, "user", "source_id", "Empty Clone")
        assert p.songs == []
        assert (sh._data_dir() / "state/spotify/empty_clone.json").exists()

    def test_sync_updates_last_synced_timestamp(self):
        songs = [make_song("A", "a")]
        import SyncZik.snapshot_handler as sh

        playlist = make_playlist(songs)
        sh.save_snapshot("spotify", playlist.service_id, songs)
        sh.save_playlist_state(playlist)
        provider = make_provider(songs)
        provider.fetch_songs.return_value = list(songs)
        assert playlist.last_synced is None
        sync(provider, playlist)
        assert playlist.last_synced is not None


# ---------------------------------------------------------------------------
# sync() — order-preserving pulls, partial-failure resilience, fetch count
# ---------------------------------------------------------------------------


class TestSyncResilience:
    def _setup(self, baseline, local, remote):
        import SyncZik.snapshot_handler as sh

        playlist = make_playlist(local)
        sh.save_snapshot("spotify", playlist.service_id, baseline)
        sh.save_playlist_state(playlist)
        return playlist

    def test_pulled_songs_preserve_remote_order(self):
        a = make_song("A", "a")
        new_songs = [make_song(x, x) for x in ["z", "m", "b"]]  # deliberately not sorted
        remote = [a] + new_songs
        playlist = self._setup(baseline=[a], local=[a], remote=remote)
        provider = make_provider(remote)
        provider.fetch_songs.return_value = list(remote)
        result = sync(provider, playlist)
        assert [s.id for s in result.added_from_remote] == ["z", "m", "b"]

    def test_push_failure_recorded_in_errors_and_not_rebaselined(self):
        a, b = make_song("A", "a"), make_song("B", "b")
        playlist = self._setup(baseline=[a], local=[a, b], remote=[a])
        provider = make_provider([a])
        provider.fetch_songs.return_value = [a]
        provider.add_songs.side_effect = RuntimeError("network error")

        result = sync(provider, playlist)

        assert result.errors
        assert b not in result.pushed_to_remote
        import SyncZik.snapshot_handler as sh

        baseline_after = sh.load_snapshot("spotify", playlist.service_id)
        assert {s.id for s in baseline_after} == {"a"}  # unchanged, b never confirmed

    def test_remove_failure_recorded_in_errors_and_not_rebaselined(self):
        a, b = make_song("A", "a"), make_song("B", "b")
        playlist = self._setup(baseline=[a, b], local=[a], remote=[a, b])
        provider = make_provider([a, b])
        provider.fetch_songs.return_value = [a, b]
        provider.remove_songs.side_effect = RuntimeError("network error")

        result = sync(provider, playlist)

        assert result.errors
        assert b not in result.removed_from_remote
        import SyncZik.snapshot_handler as sh

        baseline_after = sh.load_snapshot("spotify", playlist.service_id)
        assert {s.id for s in baseline_after} == {"a", "b"}  # unchanged, removal never confirmed

    def test_is_clean_false_when_only_errors_present(self):
        a, b = make_song("A", "a"), make_song("B", "b")
        playlist = self._setup(baseline=[a], local=[a, b], remote=[a])
        provider = make_provider([a])
        provider.fetch_songs.return_value = [a]
        provider.add_songs.side_effect = RuntimeError("network error")
        result = sync(provider, playlist)
        assert not result.is_clean()

    def test_no_push_or_remove_only_fetches_remote_once(self):
        # Pure pull, no local changes to push/remove: no need for the second
        # post-push fetch — remote_songs from the first read is already the
        # accurate new baseline.
        a, b = make_song("A", "a"), make_song("B", "b")
        playlist = self._setup(baseline=[a], local=[a], remote=[a, b])
        provider = make_provider([a, b])
        provider.fetch_songs.return_value = [a, b]
        sync(provider, playlist)
        assert provider.fetch_songs.call_count == 1

    def test_push_triggers_second_fetch(self):
        a, b = make_song("A", "a"), make_song("B", "b")
        playlist = self._setup(baseline=[a], local=[a, b], remote=[a])
        provider = make_provider([a])
        provider.fetch_songs.side_effect = [[a], [a, b]]
        sync(provider, playlist)
        assert provider.fetch_songs.call_count == 2


# ---------------------------------------------------------------------------
# rename_playlist / untrack_playlist
# ---------------------------------------------------------------------------


class TestRenamePlaylist:
    def test_renames_and_persists(self):
        p = make_playlist([make_song()])
        rename_playlist(p, "New Name")
        assert p.name == "New Name"
        import SyncZik.snapshot_handler as sh

        loaded = sh.load_playlist_state("spotify", p.service_id)
        assert loaded.name == "New Name"


class TestUntrackPlaylist:
    def test_removes_local_state(self):
        import SyncZik.snapshot_handler as sh

        p = make_playlist([make_song()])
        sh.save_playlist_state(p)
        untrack_playlist(p)
        assert sh.load_playlist_state("spotify", p.service_id) is None

    def test_removes_snapshot_history(self):
        import SyncZik.snapshot_handler as sh

        p = make_playlist([make_song()])
        sh.save_snapshot("spotify", p.service_id, p.songs)
        untrack_playlist(p)
        assert sh.list_snapshot_versions("spotify", p.service_id) == []

    def test_does_not_call_remote_provider(self):
        # untrack_playlist is local-only: it must never touch a provider.
        p = make_playlist([make_song()])
        untrack_playlist(p)  # would raise/error if it tried to use a provider argument
