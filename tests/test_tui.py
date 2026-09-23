from unittest.mock import MagicMock

import SyncZik.tui as tui
from SyncZik.providers.base import ServiceProvider
from SyncZik.providers.deezer import DeezerProvider
from SyncZik.providers.spotify import SpotifyProvider
from SyncZik.syncer import Playlist


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
