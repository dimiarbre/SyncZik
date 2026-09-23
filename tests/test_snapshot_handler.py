import json
from pathlib import Path

import pytest
from SyncZik.syncer import Artist, Song, Playlist
import SyncZik.snapshot_handler as sh
from SyncZik.snapshot_handler import (
    delete_playlist,
    list_snapshot_versions,
    migrate_legacy_storage,
    save_snapshot,
    load_snapshot,
    save_playlist_state,
    load_playlist_state,
    list_playlists,
)


def make_song(name="Track", id="s1", uri=None) -> Song:
    return Song(name=name, artists=[Artist("Artist", "a1")], uri=uri or f"spotify:track:{id}", id=id)


def make_playlist(service="spotify", service_id="pl1", songs=None) -> Playlist:
    p = Playlist(service=service, service_id=service_id, name="Test", owner="user")
    for s in (songs or []):
        p.add_song(s)
    return p


@pytest.fixture(autouse=True)
def tmp_workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SYNCZIK_DATA_DIR", str(tmp_path / "xdg_data"))


# ---------------------------------------------------------------------------
# save_snapshot / load_snapshot
# ---------------------------------------------------------------------------

class TestSnapshotRoundTrip:
    def test_save_and_load(self):
        songs = [make_song("A", "a"), make_song("B", "b")]
        save_snapshot("spotify", "pl1", songs)
        loaded = load_snapshot("spotify", "pl1")
        assert len(loaded) == 2
        assert {s.id for s in loaded} == {"a", "b"}

    def test_missing_returns_empty_list(self):
        assert load_snapshot("spotify", "nonexistent") == []

    def test_empty_list_round_trips(self):
        save_snapshot("spotify", "pl1", [])
        assert load_snapshot("spotify", "pl1") == []

    def test_creates_directory_if_missing(self):
        save_snapshot("deezer", "pl2", [make_song()])
        assert list((sh._data_dir() / "snapshots/deezer/pl2").glob("*.json"))

    def test_overwrites_existing(self):
        save_snapshot("spotify", "pl1", [make_song("Old", "old")])
        save_snapshot("spotify", "pl1", [make_song("New", "new")])
        loaded = load_snapshot("spotify", "pl1")
        assert len(loaded) == 1
        assert loaded[0].id == "new"

    def test_multi_artist_song_preserved(self):
        song = Song(
            name="Get Lucky",
            artists=[Artist("Daft Punk", "dp"), Artist("Pharrell Williams", "pw")],
            uri="spotify:track:abc",
            id="abc",
        )
        save_snapshot("spotify", "pl1", [song])
        loaded = load_snapshot("spotify", "pl1")[0]
        assert loaded.name == "Get Lucky"
        assert len(loaded.artists) == 2
        assert loaded.artists[0].name == "Daft Punk"
        assert loaded.uri == "spotify:track:abc"

    def test_multiple_playlists_independent(self):
        save_snapshot("spotify", "pl1", [make_song("A", "a")])
        save_snapshot("spotify", "pl2", [make_song("B", "b")])
        assert load_snapshot("spotify", "pl1")[0].id == "a"
        assert load_snapshot("spotify", "pl2")[0].id == "b"

    def test_different_services_independent(self):
        save_snapshot("spotify", "pl1", [make_song("A", "a")])
        save_snapshot("deezer", "pl1", [make_song("B", "b")])
        assert load_snapshot("spotify", "pl1")[0].id == "a"
        assert load_snapshot("deezer", "pl1")[0].id == "b"

    def test_unicode_song_name(self):
        song = make_song(name="Café de Flore (Remixé)", id="special1")
        save_snapshot("spotify", "pl1", [song])
        loaded = load_snapshot("spotify", "pl1")[0]
        assert loaded.name == "Café de Flore (Remixé)"


# ---------------------------------------------------------------------------
# Snapshot versioning (history) and legacy flat-file fallback
# ---------------------------------------------------------------------------

class TestSnapshotVersioning:
    def test_load_snapshot_returns_latest_version(self):
        save_snapshot("spotify", "pl1", [make_song("Old", "old")])
        save_snapshot("spotify", "pl1", [make_song("New", "new")])
        loaded = load_snapshot("spotify", "pl1")
        assert len(loaded) == 1
        assert loaded[0].id == "new"

    def test_list_snapshot_versions_newest_first(self):
        save_snapshot("spotify", "pl1", [make_song("A", "a")])
        save_snapshot("spotify", "pl1", [make_song("A", "a"), make_song("B", "b")])
        versions = list_snapshot_versions("spotify", "pl1")
        assert len(versions) == 2
        assert versions[0].timestamp > versions[1].timestamp
        assert {s.id for s in versions[0].songs} == {"a", "b"}
        assert {s.id for s in versions[1].songs} == {"a"}

    def test_list_snapshot_versions_empty_when_none_saved(self):
        assert list_snapshot_versions("spotify", "nonexistent") == []

    def test_load_snapshot_falls_back_to_legacy_flat_file(self):
        # Simulates an install from before snapshot versioning existed: a
        # flat snapshots/{service}/{id}.json file with no versioned
        # directory, already at the current data dir (i.e. after any
        # CWD -> data-dir migration has already happened).
        legacy_dir = sh._data_dir() / "snapshots" / "spotify"
        legacy_dir.mkdir(parents=True)
        (legacy_dir / "pl1.json").write_text(json.dumps([make_song("Legacy", "legacy").to_dict()]))
        loaded = load_snapshot("spotify", "pl1")
        assert len(loaded) == 1
        assert loaded[0].id == "legacy"

    def test_new_save_takes_precedence_over_legacy_file(self):
        legacy_dir = sh._data_dir() / "snapshots" / "spotify"
        legacy_dir.mkdir(parents=True)
        (legacy_dir / "pl1.json").write_text(json.dumps([make_song("Legacy", "legacy").to_dict()]))
        save_snapshot("spotify", "pl1", [make_song("New", "new")])
        loaded = load_snapshot("spotify", "pl1")
        assert loaded[0].id == "new"


# ---------------------------------------------------------------------------
# _data_dir() / migrate_legacy_storage() — CWD-relative -> XDG data dir
# ---------------------------------------------------------------------------

class TestDataDir:
    def test_respects_synczik_data_dir_env_var(self, tmp_path):
        assert sh._data_dir() == tmp_path / "xdg_data"

    def test_falls_back_to_platformdirs_when_unset(self, monkeypatch):
        monkeypatch.delenv("SYNCZIK_DATA_DIR", raising=False)
        path = sh._data_dir()
        assert "SyncZik" in str(path)


class TestMigrateLegacyStorage:
    def test_copies_legacy_state_and_snapshots(self, tmp_path):
        Path("state/spotify").mkdir(parents=True)
        Path("state/spotify/pl1.json").write_text("{}")
        Path("snapshots/spotify/pl1").mkdir(parents=True)
        Path("snapshots/spotify/pl1/20240101T000000000000.json").write_text("[]")

        migrated = migrate_legacy_storage()

        assert migrated is True
        new_state = sh._data_dir() / "state" / "spotify" / "pl1.json"
        new_snapshot = sh._data_dir() / "snapshots" / "spotify" / "pl1" / "20240101T000000000000.json"
        assert new_state.exists()
        assert new_snapshot.exists()

    def test_does_not_delete_legacy_files(self):
        Path("state/spotify").mkdir(parents=True)
        Path("state/spotify/pl1.json").write_text("{}")

        migrate_legacy_storage()

        assert Path("state/spotify/pl1.json").exists()

    def test_does_not_overwrite_existing_new_location(self):
        Path("state/spotify").mkdir(parents=True)
        Path("state/spotify/pl1.json").write_text('{"name": "legacy"}')

        new_state_dir = sh._data_dir() / "state"
        new_state_dir.mkdir(parents=True)
        (new_state_dir / "already_here.json").write_text('{"name": "fresh"}')

        migrated = migrate_legacy_storage()

        assert migrated is False
        assert (new_state_dir / "already_here.json").exists()
        assert not (new_state_dir / "spotify").exists()

    def test_returns_false_when_nothing_to_migrate(self):
        assert migrate_legacy_storage() is False

    def test_returns_false_for_empty_legacy_dirs(self):
        Path("state").mkdir()
        Path("snapshots").mkdir()
        assert migrate_legacy_storage() is False

    def test_migrated_data_is_actually_loadable(self):
        # End-to-end: old CWD-relative save, then migrate, then load via the
        # normal API should see it at the new location.
        legacy_state_dir = Path("state/spotify")
        legacy_state_dir.mkdir(parents=True)
        legacy_state_dir.joinpath("pl1.json").write_text(json.dumps(
            make_playlist(songs=[make_song()]).to_dict()
        ))

        migrate_legacy_storage()

        loaded = load_playlist_state("spotify", "pl1")
        assert loaded is not None
        assert loaded.songs[0].id == "s1"


# ---------------------------------------------------------------------------
# delete_playlist — untrack locally, remote untouched
# ---------------------------------------------------------------------------

class TestDeletePlaylist:
    def test_removes_state_file(self):
        save_playlist_state(make_playlist(songs=[make_song()]))
        delete_playlist("spotify", "pl1")
        assert load_playlist_state("spotify", "pl1") is None

    def test_removes_snapshot_history(self):
        save_snapshot("spotify", "pl1", [make_song()])
        delete_playlist("spotify", "pl1")
        assert list_snapshot_versions("spotify", "pl1") == []

    def test_removes_legacy_snapshot_file(self):
        legacy_dir = sh._data_dir() / "snapshots" / "spotify"
        legacy_dir.mkdir(parents=True)
        (legacy_dir / "pl1.json").write_text("[]")
        delete_playlist("spotify", "pl1")
        assert not (legacy_dir / "pl1.json").exists()

    def test_noop_when_nothing_tracked(self):
        delete_playlist("spotify", "ghost")  # must not raise


# ---------------------------------------------------------------------------
# Atomic writes
# ---------------------------------------------------------------------------

class TestAtomicWrite:
    def test_preserves_old_file_on_write_failure(self, monkeypatch):
        save_snapshot("spotify", "pl1", [make_song("Old", "old")])

        def boom(*args, **kwargs):
            raise RuntimeError("disk full")

        monkeypatch.setattr(sh.json, "dump", boom)
        with pytest.raises(RuntimeError):
            save_snapshot("spotify", "pl1", [make_song("New", "new")])

        loaded = load_snapshot("spotify", "pl1")
        assert loaded[0].id == "old"

    def test_no_leftover_tmp_file_after_successful_save(self):
        save_snapshot("spotify", "pl1", [make_song()])
        assert list((sh._data_dir() / "snapshots/spotify/pl1").glob("*.tmp")) == []

    def test_no_leftover_tmp_file_after_failed_save(self, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("disk full")

        monkeypatch.setattr(sh.json, "dump", boom)
        with pytest.raises(RuntimeError):
            save_snapshot("spotify", "pl1", [make_song()])

        assert list((sh._data_dir() / "snapshots/spotify/pl1").glob("*.tmp")) == []

    def test_playlist_state_write_is_also_atomic(self, monkeypatch):
        save_playlist_state(make_playlist(songs=[make_song("Old", "old")]))

        def boom(*args, **kwargs):
            raise RuntimeError("disk full")

        monkeypatch.setattr(sh.json, "dump", boom)
        with pytest.raises(RuntimeError):
            save_playlist_state(make_playlist(songs=[make_song("New", "new")]))

        loaded = load_playlist_state("spotify", "pl1")
        assert loaded.songs[0].id == "old"


# ---------------------------------------------------------------------------
# save_playlist_state / load_playlist_state
# ---------------------------------------------------------------------------

class TestPlaylistStateRoundTrip:
    def test_save_and_load(self):
        p = make_playlist(songs=[make_song("A", "a"), make_song("B", "b")])
        save_playlist_state(p)
        loaded = load_playlist_state("spotify", "pl1")
        assert loaded is not None
        assert loaded.name == "Test"
        assert len(loaded.songs) == 2

    def test_missing_returns_none(self):
        assert load_playlist_state("spotify", "ghost") is None

    def test_parent_id_preserved(self):
        p = Playlist(
            service="spotify", service_id="pl1", name="Clone", owner="u",
            parent_id="orig123", parent_service="spotify",
        )
        save_playlist_state(p)
        loaded = load_playlist_state("spotify", "pl1")
        assert loaded.parent_id == "orig123"
        assert loaded.parent_service == "spotify"

    def test_no_parent_is_none(self):
        p = make_playlist()
        save_playlist_state(p)
        loaded = load_playlist_state("spotify", "pl1")
        assert loaded.parent_id is None

    def test_last_synced_preserved(self):
        from datetime import datetime, timezone
        ts = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        p = Playlist(service="spotify", service_id="pl1", name="P", owner="u", last_synced=ts)
        save_playlist_state(p)
        loaded = load_playlist_state("spotify", "pl1")
        assert loaded.last_synced is not None
        assert loaded.last_synced.year == 2025

    def test_overwrites_existing(self):
        p = make_playlist(songs=[make_song("A", "a")])
        save_playlist_state(p)
        p.add_song(make_song("B", "b"))
        save_playlist_state(p)
        loaded = load_playlist_state("spotify", "pl1")
        assert len(loaded.songs) == 2

    def test_empty_songs_preserved(self):
        p = make_playlist(songs=[])
        save_playlist_state(p)
        loaded = load_playlist_state("spotify", "pl1")
        assert loaded.songs == []

    def test_song_order_preserved(self):
        names = ["Charlie", "Alpha", "Bravo"]
        songs = [make_song(n, n.lower()) for n in names]
        p = make_playlist(songs=songs)
        save_playlist_state(p)
        loaded = load_playlist_state("spotify", "pl1")
        assert [s.name for s in loaded.songs] == names


# ---------------------------------------------------------------------------
# list_playlists
# ---------------------------------------------------------------------------

class TestListPlaylists:
    def test_empty_when_no_state_dir(self):
        assert list_playlists() == []

    def test_single_playlist(self):
        save_playlist_state(make_playlist(songs=[make_song()]))
        result = list_playlists()
        assert len(result) == 1
        assert result[0].service_id == "pl1"

    def test_multiple_services(self):
        save_playlist_state(make_playlist(service="spotify", service_id="s1"))
        save_playlist_state(make_playlist(service="deezer", service_id="d1"))
        ids = {p.service_id for p in list_playlists()}
        assert ids == {"s1", "d1"}

    def test_multiple_playlists_same_service(self):
        for i in range(3):
            save_playlist_state(make_playlist(service_id=f"pl{i}"))
        assert len(list_playlists()) == 3

    def test_ignores_non_json_files(self):
        state_dir = sh._data_dir() / "state" / "spotify"
        state_dir.mkdir(parents=True)
        (state_dir / "README.txt").write_text("not json")
        save_playlist_state(make_playlist())
        result = list_playlists()
        assert len(result) == 1
