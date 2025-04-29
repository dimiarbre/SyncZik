import spotipy
from config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
from spotipy.oauth2 import SpotifyClientCredentials


def load_playlist(sp: spotipy.Spotify, playlist_id):
    playlist = sp.playlist(playlist_id)
    playlist_name = playlist["name"]
    playlist_owner = playlist["owner"]["display_name"]
    all_songs = []
    tracks = playlist["tracks"]
    while tracks:
        for i, song in enumerate(tracks["items"]):
            song_content = song["track"]
            all_songs.append(song)
            print(f"{len(all_songs)} {song_content['uri']} {song_content['name']}")
        if tracks["next"]:
            tracks = sp.next(tracks)
        else:
            tracks = None

    return all_songs


def main():
    auth_manager = SpotifyClientCredentials(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET)
    sp = spotipy.Spotify(auth_manager=auth_manager)

    load_playlist(sp, "2snz2HZz2ZWa6U3JK1hF19")


if __name__ == "__main__":
    main()
