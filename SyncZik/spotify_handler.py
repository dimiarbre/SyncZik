import spotipy
from config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
from spotipy.oauth2 import SpotifyClientCredentials


def load_playlist(sp: spotipy.Spotify, spotiplaylist_id):
    playlists = sp.user_playlists(spotiplaylist_id)
    raise NotImplementedError


def main():
    auth_manager = SpotifyClientCredentials(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET)
    sp = spotipy.Spotify(auth_manager=auth_manager)

    playlists = sp.user_playlists("KEMIST")
    while playlists:
        for i, playlist in enumerate(playlists["items"]):
            print(
                f"{i + 1 + playlists['offset']:4d} {playlist['uri']} {playlist['name']}"
            )
        if playlists["next"]:
            playlists = sp.next(playlists)
        else:
            playlists = None


if __name__ == "__main__":
    main()
