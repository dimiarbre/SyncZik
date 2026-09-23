import pytest

from SyncZik import auth


class TestGetSpotifyClient:
    def test_raises_when_client_id_missing(self, monkeypatch):
        monkeypatch.setattr(auth, "SPOTIFY_CLIENT_ID", None)
        monkeypatch.setattr(auth, "SPOTIFY_CLIENT_SECRET", "secret")
        monkeypatch.setattr(auth, "_spotify_client", None)

        with pytest.raises(RuntimeError, match="SPOTIFY_CLIENT_ID"):
            auth.get_spotify_client()

    def test_raises_when_client_secret_missing(self, monkeypatch):
        monkeypatch.setattr(auth, "SPOTIFY_CLIENT_ID", "id")
        monkeypatch.setattr(auth, "SPOTIFY_CLIENT_SECRET", None)
        monkeypatch.setattr(auth, "_spotify_client", None)

        with pytest.raises(RuntimeError, match="SPOTIFY_CLIENT_SECRET"):
            auth.get_spotify_client()

    def test_error_lists_both_when_both_missing(self, monkeypatch):
        monkeypatch.setattr(auth, "SPOTIFY_CLIENT_ID", None)
        monkeypatch.setattr(auth, "SPOTIFY_CLIENT_SECRET", None)
        monkeypatch.setattr(auth, "_spotify_client", None)

        with pytest.raises(RuntimeError) as exc_info:
            auth.get_spotify_client()
        assert "SPOTIFY_CLIENT_ID" in str(exc_info.value)
        assert "SPOTIFY_CLIENT_SECRET" in str(exc_info.value)

    def test_constructs_and_caches_client_when_configured(self, monkeypatch):
        monkeypatch.setattr(auth, "SPOTIFY_CLIENT_ID", "id")
        monkeypatch.setattr(auth, "SPOTIFY_CLIENT_SECRET", "secret")
        monkeypatch.setattr(auth, "_spotify_client", None)

        client1 = auth.get_spotify_client()
        client2 = auth.get_spotify_client()

        assert client1 is client2


class TestGetDeezerClient:
    def test_raises_without_token(self, monkeypatch):
        monkeypatch.setattr(auth, "DEEZER_ACCESS_TOKEN", None)
        monkeypatch.setattr(auth, "_deezer_client", None)

        with pytest.raises(RuntimeError, match="DEEZER_ACCESS_TOKEN"):
            auth.get_deezer_client()

    def test_caches_instance(self, monkeypatch):
        monkeypatch.setattr(auth, "DEEZER_ACCESS_TOKEN", "fake_token")
        monkeypatch.setattr(auth, "_deezer_client", None)

        client1 = auth.get_deezer_client()
        client2 = auth.get_deezer_client()

        assert client1 is client2
