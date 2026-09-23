from unittest.mock import MagicMock

import pytest

import SyncZik.cli as cli
from SyncZik.cross_platform import ExportPlan
from SyncZik.providers.base import ServiceProvider
from SyncZik.sync_engine import MergeResult
from SyncZik.syncer import Artist, Playlist, Song


def make_song(name="Track", id="id1") -> Song:
    return Song(name=name, artists=[Artist("Artist", "a1")], uri=f"spotify:track:{id}", id=id)


def make_playlist(service="spotify", service_id="pl1", name="Test", songs=None) -> Playlist:
    p = Playlist(service=service, service_id=service_id, name=name, owner="user")
    for s in (songs or []):
        p.add_song(s)
    return p


@pytest.fixture(autouse=True)
def tmp_workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SYNCZIK_DATA_DIR", str(tmp_path / "xdg_data"))


# ---------------------------------------------------------------------------
# _extract_id / _resolve_user_id / _find_tracked_playlist
# ---------------------------------------------------------------------------

class TestExtractId:
    def test_bare_id_unchanged(self):
        assert cli._extract_id("abc123") == "abc123"

    def test_strips_url_to_trailing_id(self):
        assert cli._extract_id("https://open.spotify.com/playlist/abc123") == "abc123"

    def test_strips_query_string(self):
        assert cli._extract_id("https://open.spotify.com/playlist/abc123?si=xyz") == "abc123"

    def test_strips_trailing_slash(self):
        assert cli._extract_id("https://open.spotify.com/playlist/abc123/") == "abc123"


class TestResolveUserId:
    def test_spotify_with_user_id(self, monkeypatch):
        monkeypatch.setattr(cli, "SPOTIFY_USER_ID", "me")
        provider = MagicMock(spec=ServiceProvider, service_name="spotify")
        assert cli._resolve_user_id(provider) == "me"

    def test_spotify_without_user_id_raises(self, monkeypatch):
        monkeypatch.setattr(cli, "SPOTIFY_USER_ID", None)
        provider = MagicMock(spec=ServiceProvider, service_name="spotify")
        with pytest.raises(SystemExit, match="SPOTIFY_USER_ID"):
            cli._resolve_user_id(provider)

    def test_deezer_returns_empty_string(self, monkeypatch):
        monkeypatch.setattr(cli, "SPOTIFY_USER_ID", None)
        provider = MagicMock(spec=ServiceProvider, service_name="deezer")
        assert cli._resolve_user_id(provider) == ""


class TestFindTrackedPlaylist:
    def test_found_by_id(self):
        p = make_playlist(service_id="pl1")
        import SyncZik.snapshot_handler as sh
        sh.save_playlist_state(p)
        found = cli._find_tracked_playlist("pl1", None)
        assert found.service_id == "pl1"

    def test_raises_when_not_found(self):
        with pytest.raises(SystemExit, match="No tracked playlist"):
            cli._find_tracked_playlist("ghost", None)

    def test_raises_when_ambiguous_across_services(self):
        import SyncZik.snapshot_handler as sh
        sh.save_playlist_state(make_playlist(service="spotify", service_id="dup"))
        sh.save_playlist_state(make_playlist(service="deezer", service_id="dup"))
        with pytest.raises(SystemExit, match="Ambiguous"):
            cli._find_tracked_playlist("dup", None)

    def test_service_disambiguates(self):
        import SyncZik.snapshot_handler as sh
        sh.save_playlist_state(make_playlist(service="spotify", service_id="dup", name="S"))
        sh.save_playlist_state(make_playlist(service="deezer", service_id="dup", name="D"))
        found = cli._find_tracked_playlist("dup", "deezer")
        assert found.name == "D"


# ---------------------------------------------------------------------------
# build_parser()
# ---------------------------------------------------------------------------

class TestBuildParser:
    def test_no_command_has_none_command(self):
        args = cli.build_parser().parse_args([])
        assert args.command is None

    def test_clone_defaults(self):
        args = cli.build_parser().parse_args(["clone", "src_id", "New Name"])
        assert args.command == "clone"
        assert args.source == "src_id"
        assert args.name == "New Name"
        assert args.service == "spotify"
        assert args.description == ""

    def test_sync_all_flag(self):
        args = cli.build_parser().parse_args(["sync", "--all"])
        assert args.all is True
        assert args.playlist_id is None

    def test_sync_playlist_id(self):
        args = cli.build_parser().parse_args(["sync", "pl1", "--service", "deezer"])
        assert args.playlist_id == "pl1"
        assert args.service == "deezer"

    def test_cherry_pick_args(self):
        args = cli.build_parser().parse_args(["cherry-pick", "target_id", "source_id"])
        assert args.target == "target_id"
        assert args.source == "source_id"

    def test_export_args(self):
        args = cli.build_parser().parse_args(["export", "src_id", "deezer", "Export Name"])
        assert args.source == "src_id"
        assert args.target_service == "deezer"
        assert args.name == "Export Name"

    def test_export_rejects_invalid_service(self):
        with pytest.raises(SystemExit):
            cli.build_parser().parse_args(["export", "src_id", "not_a_service", "Name"])


# ---------------------------------------------------------------------------
# cmd_clone
# ---------------------------------------------------------------------------

class TestCmdClone:
    def test_calls_clone_with_resolved_args(self, monkeypatch, capsys):
        provider = MagicMock(spec=ServiceProvider, service_name="spotify")
        monkeypatch.setattr(cli, "_build_provider", lambda service: provider)
        monkeypatch.setattr(cli, "SPOTIFY_USER_ID", "me")
        cloned = make_playlist(service_id="new1", name="New Name", songs=[make_song()])
        clone_mock = MagicMock(return_value=cloned)
        monkeypatch.setattr(cli, "clone_playlist", clone_mock)

        args = cli.build_parser().parse_args(["clone", "https://x/playlist/src_id", "New Name"])
        result = cli.cmd_clone(args)

        assert result == 0
        clone_mock.assert_called_once_with(provider, "me", "src_id", "New Name", description="")
        assert "New Name" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# cmd_sync
# ---------------------------------------------------------------------------

class TestCmdSync:
    def test_requires_playlist_id_or_all(self):
        args = cli.build_parser().parse_args(["sync"])
        with pytest.raises(SystemExit, match="--all"):
            cli.cmd_sync(args)

    def test_syncs_single_playlist(self, monkeypatch, capsys):
        p = make_playlist(service_id="pl1")
        import SyncZik.snapshot_handler as sh
        sh.save_playlist_state(p)

        provider = MagicMock(spec=ServiceProvider)
        monkeypatch.setattr(cli, "_build_provider", lambda service: provider)
        monkeypatch.setattr(cli, "sync_playlist", lambda provider, playlist: MergeResult())

        args = cli.build_parser().parse_args(["sync", "pl1"])
        result = cli.cmd_sync(args)

        assert result == 0
        assert "up to date" in capsys.readouterr().out

    def test_all_syncs_every_tracked_playlist(self, monkeypatch):
        import SyncZik.snapshot_handler as sh
        sh.save_playlist_state(make_playlist(service_id="a"))
        sh.save_playlist_state(make_playlist(service_id="b"))

        sync_mock = MagicMock(return_value=MergeResult())
        monkeypatch.setattr(cli, "_build_provider", lambda service: MagicMock(spec=ServiceProvider))
        monkeypatch.setattr(cli, "sync_playlist", sync_mock)

        args = cli.build_parser().parse_args(["sync", "--all"])
        result = cli.cmd_sync(args)

        assert result == 0
        assert sync_mock.call_count == 2

    def test_all_with_no_tracked_playlists_is_noop(self, capsys):
        args = cli.build_parser().parse_args(["sync", "--all"])
        result = cli.cmd_sync(args)
        assert result == 0
        assert "No tracked playlists" in capsys.readouterr().out

    def test_result_errors_set_nonzero_exit_code(self, monkeypatch, capsys):
        import SyncZik.snapshot_handler as sh
        sh.save_playlist_state(make_playlist(service_id="pl1"))

        bad_result = MergeResult(errors=["push failed: boom"])
        monkeypatch.setattr(cli, "_build_provider", lambda service: MagicMock(spec=ServiceProvider))
        monkeypatch.setattr(cli, "sync_playlist", lambda provider, playlist: bad_result)

        args = cli.build_parser().parse_args(["sync", "pl1"])
        result = cli.cmd_sync(args)

        assert result == 1
        assert "boom" in capsys.readouterr().err

    def test_sync_exception_sets_nonzero_exit_code_and_continues(self, monkeypatch, capsys):
        import SyncZik.snapshot_handler as sh
        sh.save_playlist_state(make_playlist(service_id="a"))
        sh.save_playlist_state(make_playlist(service_id="b"))

        def sync_side_effect(provider, playlist):
            if playlist.service_id == "a":
                raise RuntimeError("network error")
            return MergeResult()

        monkeypatch.setattr(cli, "_build_provider", lambda service: MagicMock(spec=ServiceProvider))
        monkeypatch.setattr(cli, "sync_playlist", sync_side_effect)

        args = cli.build_parser().parse_args(["sync", "--all"])
        result = cli.cmd_sync(args)

        assert result == 1
        assert "network error" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# cmd_cherry_pick
# ---------------------------------------------------------------------------

class TestCmdCherryPick:
    def test_cherry_picks_new_songs_into_target(self, monkeypatch, capsys):
        target = make_playlist(service_id="target1", name="Target")
        import SyncZik.snapshot_handler as sh
        sh.save_playlist_state(target)

        songs = [make_song("A", "a"), make_song("B", "b")]
        monkeypatch.setattr(cli, "_build_provider", lambda service: MagicMock(spec=ServiceProvider))
        monkeypatch.setattr(cli, "songs_in_playlist", lambda provider, source_id: songs)

        args = cli.build_parser().parse_args(["cherry-pick", "target1", "source_id"])
        result = cli.cmd_cherry_pick(args)

        assert result == 0
        out = capsys.readouterr().out
        assert "2" in out
        loaded = sh.load_playlist_state("spotify", "target1")
        assert {s.id for s in loaded.songs} == {"a", "b"}


# ---------------------------------------------------------------------------
# cmd_export
# ---------------------------------------------------------------------------

class TestCmdExport:
    def test_exports_auto_resolved_songs(self, monkeypatch, capsys):
        source = make_playlist(service_id="src1", name="Source", songs=[make_song("A", "a")])
        import SyncZik.snapshot_handler as sh
        sh.save_playlist_state(source)

        target_provider = MagicMock(spec=ServiceProvider, service_name="deezer")
        monkeypatch.setattr(cli, "_build_provider", lambda service: target_provider)
        monkeypatch.setattr(cli, "SPOTIFY_USER_ID", "me")
        auto_resolved_song = make_song("A", "d1")
        monkeypatch.setattr(
            cli, "plan_export",
            lambda songs, provider: ExportPlan(auto_resolved=[(songs[0], auto_resolved_song)]),
        )
        execute_mock = MagicMock(return_value="new_export_id")
        monkeypatch.setattr(cli, "execute_export", execute_mock)

        args = cli.build_parser().parse_args(["export", "src1", "deezer", "My Export"])
        result = cli.cmd_export(args)

        assert result == 0
        execute_mock.assert_called_once()
        out = capsys.readouterr().out
        assert "My Export" in out
        assert "new_export_id" in out

    def test_reports_skipped_conflicts(self, monkeypatch, capsys):
        source = make_playlist(service_id="src1", songs=[make_song("A", "a"), make_song("B", "b")])
        import SyncZik.snapshot_handler as sh
        sh.save_playlist_state(source)

        target_provider = MagicMock(spec=ServiceProvider, service_name="deezer")
        monkeypatch.setattr(cli, "_build_provider", lambda service: target_provider)
        monkeypatch.setattr(cli, "SPOTIFY_USER_ID", "me")
        from SyncZik.cross_platform import MatchKind, SongConflict
        plan = ExportPlan(
            auto_resolved=[(source.songs[0], make_song("A", "d1"))],
            conflicts=[SongConflict(source=source.songs[1], kind=MatchKind.NOT_FOUND)],
        )
        monkeypatch.setattr(cli, "plan_export", lambda songs, provider: plan)
        monkeypatch.setattr(cli, "execute_export", MagicMock(return_value="id"))

        args = cli.build_parser().parse_args(["export", "src1", "deezer", "Name"])
        cli.cmd_export(args)

        assert "1 skipped" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# run_cli — top-level dispatch
# ---------------------------------------------------------------------------

class TestRunCli:
    def test_no_args_returns_none(self, monkeypatch):
        monkeypatch.setattr(cli, "setup_logging", MagicMock())
        assert cli.run_cli([]) is None

    def test_successful_subcommand_returns_zero(self, monkeypatch):
        monkeypatch.setattr(cli, "setup_logging", MagicMock())
        monkeypatch.setattr(cli, "_build_provider", lambda service: MagicMock(spec=ServiceProvider))
        monkeypatch.setattr(cli, "sync_playlist", lambda provider, playlist: MergeResult())
        import SyncZik.snapshot_handler as sh
        sh.save_playlist_state(make_playlist(service_id="pl1"))

        assert cli.run_cli(["sync", "pl1"]) == 0

    def test_unexpected_exception_is_caught_and_reported(self, monkeypatch, capsys):
        monkeypatch.setattr(cli, "setup_logging", MagicMock())

        def boom(args):
            raise RuntimeError("kaboom")

        monkeypatch.setattr(cli, "cmd_clone", boom)
        result = cli.run_cli(["clone", "src", "name"])

        assert result == 1
        assert "kaboom" in capsys.readouterr().err

    def test_invalid_subcommand_exits_via_argparse(self, monkeypatch):
        monkeypatch.setattr(cli, "setup_logging", MagicMock())
        with pytest.raises(SystemExit):
            cli.run_cli(["not-a-real-command"])
