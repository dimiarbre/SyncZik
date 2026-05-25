import spotipy
from spotipy.oauth2 import SpotifyOAuth

from config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_REDIRECT_URI

_SCOPES = " ".join([
    "playlist-modify-public",
    "playlist-modify-private",
    "playlist-read-private",
    "playlist-read-collaborative",
    "user-library-read",
])

_spotify_client: spotipy.Spotify | None = None


def get_spotify_client() -> spotipy.Spotify:
    """Return a cached, OAuth-authenticated Spotify client.

    On first call the browser opens for the user to log in. The token is then
    cached to .spotify_cache and refreshed automatically on subsequent calls.
    """
    global _spotify_client
    if _spotify_client is None:
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
