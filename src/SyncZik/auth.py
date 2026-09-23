import deezer
import spotipy
from spotipy.oauth2 import SpotifyOAuth

from .config import (
    DEEZER_ACCESS_TOKEN,
    SPOTIFY_CLIENT_ID,
    SPOTIFY_CLIENT_SECRET,
    SPOTIFY_REDIRECT_URI,
)

_SCOPES = " ".join(
    [
        "playlist-modify-public",
        "playlist-modify-private",
        "playlist-read-private",
        "playlist-read-collaborative",
        "user-library-read",
    ]
)

_spotify_client: spotipy.Spotify | None = None


def get_spotify_client() -> spotipy.Spotify:
    """Return a cached, OAuth-authenticated Spotify client.

    On first call the browser opens for the user to log in. The token is then
    cached to .spotify_cache and refreshed automatically on subsequent calls.
    """
    global _spotify_client
    if _spotify_client is None:
        missing = [
            name
            for name, value in (
                ("SPOTIFY_CLIENT_ID", SPOTIFY_CLIENT_ID),
                ("SPOTIFY_CLIENT_SECRET", SPOTIFY_CLIENT_SECRET),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(
                "Missing required .env variable(s) for Spotify: "
                + ", ".join(missing)
                + ". Copy .env.example to .env and fill it in — see README's Setup section."
            )
        auth_manager = SpotifyOAuth(
            client_id=SPOTIFY_CLIENT_ID,
            client_secret=SPOTIFY_CLIENT_SECRET,
            redirect_uri=SPOTIFY_REDIRECT_URI,
            scope=_SCOPES,
            cache_path=".spotify_cache",
            open_browser=True,
        )
        _spotify_client = spotipy.Spotify(auth_manager=auth_manager)
    return _spotify_client


_deezer_client: deezer.Client | None = None


def get_deezer_client() -> deezer.Client:
    """Return a cached Deezer client authenticated with DEEZER_ACCESS_TOKEN.

    Unlike Spotify there is no OAuth dance to perform here: the user must obtain
    a Deezer access token manually (register an app at developers.deezer.com,
    complete the OAuth authorize redirect once, and paste the resulting token
    into .env) before running SyncZik. See README for details.
    """
    global _deezer_client
    if _deezer_client is None:
        if not DEEZER_ACCESS_TOKEN:
            raise RuntimeError(
                "DEEZER_ACCESS_TOKEN not set in .env. See README for how to obtain a Deezer access token."
            )
        _deezer_client = deezer.Client(access_token=DEEZER_ACCESS_TOKEN)
    return _deezer_client
