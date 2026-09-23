import asyncio
from unittest.mock import MagicMock

import pytest
from textual.widgets import Input

import SyncZik.snapshot_handler as sh
import SyncZik.tui as tui
from SyncZik.providers.base import ServiceProvider
from SyncZik.providers.deezer import DeezerProvider
from SyncZik.providers.spotify import SpotifyProvider
from SyncZik.sync_engine import MergeResult
from SyncZik.syncer import Artist, Playlist, Song


@pytest.fixture(autouse=True)
def tmp_workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SYNCZIK_DATA_DIR", str(tmp_path / "xdg_data"))


def make_song(name="Track", id="id1") -> Song:
    return Song(name=name, artists=[Artist("Artist", "a1")], uri=f"spotify:track:{id}", id=id)


async def _boot(monkeypatch, pilot):
    """Dismiss the startup provider-picker (falls back to Spotify) with real
    clients mocked out so no network/OAuth call happens."""
    monkeypatch.setattr(tui, "get_spotify_client", lambda: MagicMock())
    monkeypatch.setattr(tui, "get_deezer_client", lambda: MagicMock())
    await pilot.press("escape")
    await pilot.pause()


# ---------------------------------------------------------------------------
# build_provider
# ---------------------------------------------------------------------------

class TestBuildProvider:
    def test_deezer_choice_returns_deezer_provider(self, monkeypatch):
        sentinel = MagicMock()
        monkeypatch.setattr(tui, "get_deezer_client", lambda: sentinel)
        provider = tui.build_provider("deezer")
        assert isinstance(provider, DeezerProvider)

    def test_spotify_choice_returns_spotify_provider(self, monkeypatch):
        sentinel = MagicMock()
        monkeypatch.setattr(tui, "get_spotify_client", lambda: sentinel)
        provider = tui.build_provider("spotify")
        assert isinstance(provider, SpotifyProvider)

    def test_missing_deezer_token_propagates_runtime_error(self, monkeypatch):
        def raise_missing_token():
            raise RuntimeError("DEEZER_ACCESS_TOKEN not set in .env.")

        monkeypatch.setattr(tui, "get_deezer_client", raise_missing_token)
        try:
            tui.build_provider("deezer")
            assert False, "expected RuntimeError"
        except RuntimeError as e:
            assert "DEEZER_ACCESS_TOKEN" in str(e)


# ---------------------------------------------------------------------------
# resolve_clone_user_id
# ---------------------------------------------------------------------------

class TestResolveCloneUserId:
    def test_spotify_with_user_id_configured(self, monkeypatch):
        monkeypatch.setattr(tui, "SPOTIFY_USER_ID", "spotify_user_123")
        provider = MagicMock(spec=ServiceProvider, service_name="spotify")
        assert tui.resolve_clone_user_id(provider) == "spotify_user_123"

    def test_spotify_without_user_id_configured_returns_none(self, monkeypatch):
        monkeypatch.setattr(tui, "SPOTIFY_USER_ID", None)
        provider = MagicMock(spec=ServiceProvider, service_name="spotify")
        assert tui.resolve_clone_user_id(provider) is None

    def test_deezer_ignores_spotify_user_id(self, monkeypatch):
        monkeypatch.setattr(tui, "SPOTIFY_USER_ID", None)
        provider = MagicMock(spec=ServiceProvider, service_name="deezer")
        assert tui.resolve_clone_user_id(provider) == ""


# ---------------------------------------------------------------------------
# Modals accept a generic ServiceProvider (regression guard for the
# SpotifyProvider -> ServiceProvider type-hint widening)
# ---------------------------------------------------------------------------

class TestModalsAcceptGenericProvider:
    def test_search_modal_construction(self):
        provider = MagicMock(spec=ServiceProvider)
        modal = tui.SearchModal(provider)
        assert modal._provider is provider

    def test_cherry_pick_modal_construction(self):
        provider = MagicMock(spec=ServiceProvider)
        target = Playlist(service="deezer", service_id="pl1", name="Test", owner="user")
        modal = tui.CherryPickModal(provider, target)
        assert modal._provider is provider
        assert modal._target is target


# ---------------------------------------------------------------------------
# run_blocking — the async worker helper behind Load/Clone/Sync/Search/
# Export/Cherry-pick's non-blocking network calls
# ---------------------------------------------------------------------------

class TestRunBlocking:
    def test_returns_function_result(self):
        async def scenario():
            app = tui.SyncZikApp()
            async with app.run_test():
                result = await tui.run_blocking(app, lambda: 42)
                assert result == 42

        asyncio.run(scenario())

    def test_reraises_original_exception_not_workerfailed(self):
        async def scenario():
            app = tui.SyncZikApp()
            async with app.run_test():
                def boom():
                    raise ValueError("network error")

                with pytest.raises(ValueError, match="network error"):
                    await tui.run_blocking(app, boom)

        asyncio.run(scenario())


# ---------------------------------------------------------------------------
# action_undo — one-level undo for the last staged add/remove/cherry-pick
# ---------------------------------------------------------------------------

class TestActionUndo:
    def test_nothing_to_undo_warns(self, monkeypatch):
        async def scenario():
            app = tui.SyncZikApp()
            async with app.run_test() as pilot:
                await _boot(monkeypatch, pilot)
                notify = MagicMock()
                monkeypatch.setattr(app, "notify", notify)
                app.action_undo()
                notify.assert_called_once()
                assert notify.call_args[0][0] == "Nothing to undo."

        asyncio.run(scenario())

    def test_undo_add_removes_staged_song(self, monkeypatch):
        async def scenario():
            app = tui.SyncZikApp()
            async with app.run_test() as pilot:
                await _boot(monkeypatch, pilot)
                song = make_song()
                playlist = Playlist(service="spotify", service_id="pl1", name="P", owner="u")
                playlist.add_song(song)
                app._last_action = ("add", playlist, [song])

                app.action_undo()

                assert song not in playlist.songs
                assert app._last_action is None

        asyncio.run(scenario())

    def test_undo_remove_restores_staged_song(self, monkeypatch):
        async def scenario():
            app = tui.SyncZikApp()
            async with app.run_test() as pilot:
                await _boot(monkeypatch, pilot)
                song = make_song()
                playlist = Playlist(service="spotify", service_id="pl1", name="P", owner="u")
                app._last_action = ("remove", playlist, [song])

                app.action_undo()

                assert song in playlist.songs
                assert app._last_action is None

        asyncio.run(scenario())


# ---------------------------------------------------------------------------
# action_diff_playlists — wires playlist_git.diff() into the TUI
# ---------------------------------------------------------------------------

class TestActionDiffPlaylists:
    def test_warns_when_nothing_selected(self, monkeypatch):
        async def scenario():
            app = tui.SyncZikApp()
            async with app.run_test() as pilot:
                await _boot(monkeypatch, pilot)
                notify = MagicMock()
                monkeypatch.setattr(app, "notify", notify)
                app.action_diff_playlists()
                notify.assert_called_once()

        asyncio.run(scenario())

    def test_warns_when_no_other_tracked_playlist(self, monkeypatch):
        async def scenario():
            app = tui.SyncZikApp()
            async with app.run_test() as pilot:
                await _boot(monkeypatch, pilot)
                playlist = Playlist(service="spotify", service_id="pl1", name="P", owner="u")
                app._selected = playlist
                app._playlists = [playlist]
                notify = MagicMock()
                monkeypatch.setattr(app, "notify", notify)
                app.action_diff_playlists()
                notify.assert_called_once()

        asyncio.run(scenario())

    def test_pushes_playlist_picker_when_others_exist(self, monkeypatch):
        async def scenario():
            app = tui.SyncZikApp()
            async with app.run_test() as pilot:
                await _boot(monkeypatch, pilot)
                a = Playlist(service="spotify", service_id="a", name="A", owner="u")
                b = Playlist(service="spotify", service_id="b", name="B", owner="u")
                app._selected = a
                app._playlists = [a, b]
                app.action_diff_playlists()
                await pilot.pause()
                assert isinstance(app.screen, tui.PlaylistPickerModal)

        asyncio.run(scenario())

    def test_diff_result_modal_shows_symmetric_difference(self, monkeypatch):
        async def scenario():
            app = tui.SyncZikApp()
            async with app.run_test() as pilot:
                await _boot(monkeypatch, pilot)
                shared = make_song("Shared", "shared")
                only_a = make_song("OnlyA", "only_a")
                only_b = make_song("OnlyB", "only_b")
                a = Playlist(service="spotify", service_id="a", name="A", owner="u")
                a.songs = [shared, only_a]
                b = Playlist(service="spotify", service_id="b", name="B", owner="u")
                b.songs = [shared, only_b]

                result = tui.diff(a, b)
                app.push_screen(tui.DiffResultModal(a, b, result))
                await pilot.pause()

                modal = app.screen
                assert isinstance(modal, tui.DiffResultModal)
                summary = str(modal.query_one("#diff-summary").content)
                assert "1" in summary  # one song only in each side

        asyncio.run(scenario())


# ---------------------------------------------------------------------------
# SyncResultModal — per-song pending-removal decisions
# ---------------------------------------------------------------------------

class TestSyncResultModalPerSong:
    def test_toggle_marks_single_song_for_removal(self, monkeypatch):
        async def scenario():
            app = tui.SyncZikApp()
            async with app.run_test() as pilot:
                await _boot(monkeypatch, pilot)
                song_a, song_b = make_song("A", "a"), make_song("B", "b")
                result = MergeResult(removed_from_remote_pending=[song_a, song_b])
                dismissed = []
                app.push_screen(tui.SyncResultModal(result), dismissed.append)
                await pilot.pause()

                modal = app.screen
                modal._toggle(0)
                await pilot.click("#done")
                await pilot.pause()

                assert [s.id for s in dismissed[0]] == ["a"]

        asyncio.run(scenario())

    def test_remove_all_button_marks_every_pending_song(self, monkeypatch):
        async def scenario():
            app = tui.SyncZikApp()
            async with app.run_test() as pilot:
                await _boot(monkeypatch, pilot)
                song_a, song_b = make_song("A", "a"), make_song("B", "b")
                result = MergeResult(removed_from_remote_pending=[song_a, song_b])
                dismissed = []
                app.push_screen(tui.SyncResultModal(result), dismissed.append)
                await pilot.pause()

                await pilot.click("#remove-all")
                await pilot.click("#done")
                await pilot.pause()

                assert {s.id for s in dismissed[0]} == {"a", "b"}

        asyncio.run(scenario())

    def test_keep_all_after_toggle_clears_selection(self, monkeypatch):
        async def scenario():
            app = tui.SyncZikApp()
            async with app.run_test() as pilot:
                await _boot(monkeypatch, pilot)
                song_a = make_song("A", "a")
                result = MergeResult(removed_from_remote_pending=[song_a])
                dismissed = []
                app.push_screen(tui.SyncResultModal(result), dismissed.append)
                await pilot.pause()

                modal = app.screen
                modal._toggle(0)
                await pilot.click("#keep-all")
                await pilot.click("#done")
                await pilot.pause()

                assert dismissed[0] == []

        asyncio.run(scenario())

    def test_escape_keeps_all_pending_songs(self, monkeypatch):
        async def scenario():
            app = tui.SyncZikApp()
            async with app.run_test() as pilot:
                await _boot(monkeypatch, pilot)
                song_a = make_song("A", "a")
                result = MergeResult(removed_from_remote_pending=[song_a])
                dismissed = []
                app.push_screen(tui.SyncResultModal(result), dismissed.append)
                await pilot.pause()

                modal = app.screen
                modal._toggle(0)  # mark for removal, then back out via Escape
                await pilot.press("escape")
                await pilot.pause()

                assert dismissed[0] == []

        asyncio.run(scenario())


# ---------------------------------------------------------------------------
# CherryPickModal — async fetch off the UI thread, and the Space-toggle fix
# (previously the on-screen hint said "Space to toggle" but ListView only
# bound Enter by default, so Space silently did nothing)
# ---------------------------------------------------------------------------

class TestCherryPickModalAsyncAndToggle:
    def test_fetch_runs_off_thread_and_populates_candidates(self, monkeypatch):
        async def scenario():
            app = tui.SyncZikApp()
            async with app.run_test() as pilot:
                await _boot(monkeypatch, pilot)
                song_a, song_b = make_song("A", "a"), make_song("B", "b")
                monkeypatch.setattr(tui, "songs_in_playlist", lambda provider, raw: [song_a, song_b])

                provider = MagicMock(spec=ServiceProvider)
                target = Playlist(service="spotify", service_id="t1", name="Target", owner="u")
                modal = tui.CherryPickModal(provider, target)
                app.push_screen(modal)
                await pilot.pause()

                input_widget = modal.query_one("#pick-input", Input)
                await modal.on_input_submitted(Input.Submitted(input_widget, "some_id"))
                await pilot.pause()

                assert {s.id for s in modal._candidates} == {"a", "b"}

        asyncio.run(scenario())

    def test_space_toggle_matches_enter_toggle_behavior(self, monkeypatch):
        async def scenario():
            app = tui.SyncZikApp()
            async with app.run_test() as pilot:
                await _boot(monkeypatch, pilot)
                song_a = make_song("A", "a")
                monkeypatch.setattr(tui, "songs_in_playlist", lambda provider, raw: [song_a])

                provider = MagicMock(spec=ServiceProvider)
                target = Playlist(service="spotify", service_id="t1", name="Target", owner="u")
                modal = tui.CherryPickModal(provider, target)
                app.push_screen(modal)
                await pilot.pause()

                input_widget = modal.query_one("#pick-input", Input)
                await modal.on_input_submitted(Input.Submitted(input_widget, "some_id"))
                await pilot.pause()

                from textual.widgets import ListView
                lv = modal.query_one("#pick-list", ListView)
                lv.index = 0

                # Space (action_toggle_current) is the fix under test: it must
                # select the same song Enter (on_list_view_selected) would.
                modal.action_toggle_current()
                assert song_a.id in modal._selected_ids
                modal.action_toggle_current()
                assert song_a.id not in modal._selected_ids

        asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Escape-to-cancel on modals
# ---------------------------------------------------------------------------

class TestEscapeToCancel:
    def test_input_modal_escape_dismisses_with_none(self, monkeypatch):
        async def scenario():
            app = tui.SyncZikApp()
            async with app.run_test() as pilot:
                await _boot(monkeypatch, pilot)
                dismissed = []
                app.push_screen(tui.InputModal("Title", "ph"), dismissed.append)
                await pilot.pause()
                await pilot.press("escape")
                await pilot.pause()
                assert dismissed == [None]

        asyncio.run(scenario())

    def test_provider_picker_modal_escape_dismisses_with_none(self, monkeypatch):
        async def scenario():
            app = tui.SyncZikApp()
            async with app.run_test() as pilot:
                await _boot(monkeypatch, pilot)
                dismissed = []
                app.push_screen(tui.ProviderPickerModal(), dismissed.append)
                await pilot.pause()
                await pilot.press("escape")
                await pilot.pause()
                assert dismissed == [None]

        asyncio.run(scenario())

    def test_cherry_pick_modal_escape_dismisses_with_empty_list(self, monkeypatch):
        async def scenario():
            app = tui.SyncZikApp()
            async with app.run_test() as pilot:
                await _boot(monkeypatch, pilot)
                provider = MagicMock(spec=ServiceProvider)
                target = Playlist(service="spotify", service_id="t1", name="Target", owner="u")
                dismissed = []
                app.push_screen(tui.CherryPickModal(provider, target), dismissed.append)
                await pilot.pause()
                await pilot.press("escape")
                await pilot.pause()
                assert dismissed == [[]]

        asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Help screen
# ---------------------------------------------------------------------------

class TestHelpScreen:
    def test_action_show_help_pushes_help_modal(self, monkeypatch):
        async def scenario():
            app = tui.SyncZikApp()
            async with app.run_test() as pilot:
                await _boot(monkeypatch, pilot)
                app.action_show_help()
                await pilot.pause()
                assert isinstance(app.screen, tui.HelpModal)

        asyncio.run(scenario())

    def test_question_mark_key_opens_help(self, monkeypatch):
        async def scenario():
            app = tui.SyncZikApp()
            async with app.run_test() as pilot:
                await _boot(monkeypatch, pilot)
                await pilot.press("question_mark")
                await pilot.pause()
                assert isinstance(app.screen, tui.HelpModal)

        asyncio.run(scenario())


# ---------------------------------------------------------------------------
# First-run onboarding hint
# ---------------------------------------------------------------------------

class TestFirstRunHint:
    def test_empty_playlist_tree_shows_onboarding_hint(self, monkeypatch):
        async def scenario():
            app = tui.SyncZikApp()
            async with app.run_test() as pilot:
                await _boot(monkeypatch, pilot)
                from textual.widgets import Tree
                tree = app.query_one("#playlist-tree", Tree)
                labels = [str(child.label) for child in tree.root.children]
                assert any("press L to load" in label for label in labels)

        asyncio.run(scenario())


# ---------------------------------------------------------------------------
# action_history / HistoryModal — log + revert wired into the TUI
# ---------------------------------------------------------------------------

class TestActionHistory:
    def test_warns_when_nothing_selected(self, monkeypatch):
        async def scenario():
            app = tui.SyncZikApp()
            async with app.run_test() as pilot:
                await _boot(monkeypatch, pilot)
                notify = MagicMock()
                monkeypatch.setattr(app, "notify", notify)
                app.action_history()
                notify.assert_called_once()

        asyncio.run(scenario())

    def test_pushes_history_modal_with_no_entries_message(self, monkeypatch):
        async def scenario():
            app = tui.SyncZikApp()
            async with app.run_test() as pilot:
                await _boot(monkeypatch, pilot)
                playlist = Playlist(service="spotify", service_id="pl1", name="P", owner="u")
                app._selected = playlist
                app.action_history()
                await pilot.pause()
                modal = app.screen
                assert isinstance(modal, tui.HistoryModal)
                assert modal._entries == []

        asyncio.run(scenario())

    def test_revert_restores_local_state_and_dismisses_true(self, monkeypatch):
        async def scenario():
            app = tui.SyncZikApp()
            async with app.run_test() as pilot:
                await _boot(monkeypatch, pilot)
                a, b = make_song("A", "a"), make_song("B", "b")
                sh.save_snapshot("spotify", "pl1", [a])
                sh.save_snapshot("spotify", "pl1", [a, b])
                playlist = Playlist(service="spotify", service_id="pl1", name="P", owner="u")
                playlist.songs = [a, b]
                sh.save_playlist_state(playlist)
                app._selected = playlist

                dismissed = []
                entries = tui.log("spotify", "pl1")
                app.push_screen(tui.HistoryModal(playlist, entries), dismissed.append)
                await pilot.pause()

                lv = app.screen.query_one("#history-list")
                lv.index = 1  # the older, single-song version
                await pilot.click("#revert")
                await pilot.pause()

                assert dismissed == [True]
                assert {s.id for s in playlist.songs} == {"a"}

        asyncio.run(scenario())

    def test_close_dismisses_false_without_reverting(self, monkeypatch):
        async def scenario():
            app = tui.SyncZikApp()
            async with app.run_test() as pilot:
                await _boot(monkeypatch, pilot)
                a = make_song("A", "a")
                sh.save_snapshot("spotify", "pl1", [a])
                playlist = Playlist(service="spotify", service_id="pl1", name="P", owner="u")
                playlist.songs = [a]

                dismissed = []
                entries = tui.log("spotify", "pl1")
                app.push_screen(tui.HistoryModal(playlist, entries), dismissed.append)
                await pilot.pause()
                await pilot.click("#close")
                await pilot.pause()

                assert dismissed == [False]

        asyncio.run(scenario())


# ---------------------------------------------------------------------------
# action_rename_playlist
# ---------------------------------------------------------------------------

class TestActionRenamePlaylist:
    def test_warns_when_nothing_selected(self, monkeypatch):
        async def scenario():
            app = tui.SyncZikApp()
            async with app.run_test() as pilot:
                await _boot(monkeypatch, pilot)
                notify = MagicMock()
                monkeypatch.setattr(app, "notify", notify)
                app.action_rename_playlist()
                notify.assert_called_once()

        asyncio.run(scenario())

    def test_renames_and_persists(self, monkeypatch):
        async def scenario():
            app = tui.SyncZikApp()
            async with app.run_test() as pilot:
                await _boot(monkeypatch, pilot)
                playlist = Playlist(service="spotify", service_id="pl1", name="Old Name", owner="u")
                sh.save_playlist_state(playlist)
                app._selected = playlist

                app.action_rename_playlist()
                await pilot.pause()
                input_widget = app.screen.query_one("#dialog-input", Input)
                input_widget.value = "New Name"
                await pilot.press("enter")
                await pilot.pause()

                assert playlist.name == "New Name"
                loaded = sh.load_playlist_state("spotify", "pl1")
                assert loaded.name == "New Name"

        asyncio.run(scenario())


# ---------------------------------------------------------------------------
# action_untrack_playlist / ConfirmModal
# ---------------------------------------------------------------------------

class TestActionUntrackPlaylist:
    def test_warns_when_nothing_selected(self, monkeypatch):
        async def scenario():
            app = tui.SyncZikApp()
            async with app.run_test() as pilot:
                await _boot(monkeypatch, pilot)
                notify = MagicMock()
                monkeypatch.setattr(app, "notify", notify)
                app.action_untrack_playlist()
                notify.assert_called_once()

        asyncio.run(scenario())

    def test_cancel_leaves_playlist_tracked(self, monkeypatch):
        async def scenario():
            app = tui.SyncZikApp()
            async with app.run_test() as pilot:
                await _boot(monkeypatch, pilot)
                playlist = Playlist(service="spotify", service_id="pl1", name="P", owner="u")
                sh.save_playlist_state(playlist)
                app._selected = playlist

                app.action_untrack_playlist()
                await pilot.pause()
                await pilot.click("#cancel")
                await pilot.pause()

                assert sh.load_playlist_state("spotify", "pl1") is not None
                assert app._selected is playlist

        asyncio.run(scenario())

    def test_confirm_untracks_and_clears_selection(self, monkeypatch):
        async def scenario():
            app = tui.SyncZikApp()
            async with app.run_test() as pilot:
                await _boot(monkeypatch, pilot)
                playlist = Playlist(service="spotify", service_id="pl1", name="P", owner="u")
                sh.save_playlist_state(playlist)
                app._selected = playlist

                app.action_untrack_playlist()
                await pilot.pause()
                await pilot.click("#yes")
                await pilot.pause()

                assert sh.load_playlist_state("spotify", "pl1") is None
                assert app._selected is None

        asyncio.run(scenario())
