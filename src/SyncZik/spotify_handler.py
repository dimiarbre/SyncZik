import spotipy
from config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
from spotipy.oauth2 import SpotifyClientCredentials


def load_playlist(playlist_id, spotify_client_id, spotify_client_secret):
    # Instanciate Spotipy API
    auth_manager = SpotifyClientCredentials(spotify_client_id, spotify_client_secret)
    sp = spotipy.Spotify(auth_manager=auth_manager)

    # Request playlist
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

    load_playlist("2snz2HZz2ZWa6U3JK1hF19", SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET)


if __name__ == "__main__":
    main()
