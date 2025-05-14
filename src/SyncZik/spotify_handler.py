import spotipy
from config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
from snapshot_handler import get_file_location, load_snapshot, save_snapshot
from spotipy.oauth2 import SpotifyClientCredentials
from syncer import Artist, Playslist, Song


def parse_artists(artists_json) -> list[Artist]:
    artists = []
    for artist in artists_json:
        name = artist["name"]
        id = artist["id"]
        artists.append(Artist(name, id))
    return artists


def parse_song(song) -> Song:
    song_content = song["track"]
    song_name = song_content["name"]
    artists = parse_artists(song_content["artists"])
    added_by = song["added_by"]["id"]
    id = song_content["id"]
    uri = song_content["uri"]

    parsed_song = Song(name=song_name, artists=artists, uri=uri, id=id)
    return parsed_song


def parse_playlist(playlist_id, spotify_client_id, spotify_client_secret):
    # Instanciate Spotipy API
    auth_manager = SpotifyClientCredentials(spotify_client_id, spotify_client_secret)
    sp = spotipy.Spotify(auth_manager=auth_manager)

    # Request playlist
    playlist = sp.playlist(playlist_id)

    playlist_name = playlist["name"]
    playlist_owner = playlist["owner"]["display_name"]

    playlist = Playslist(
        playlist_name=playlist_name,
        playlist_id=playlist_id,
        playlist_owner=playlist_owner,
    )
    all_songs = []
    tracks = playlist["tracks"]
    while tracks:
        for i, song in enumerate(tracks["items"]):
            parsed_song = parse_song(song)
            is_added = playlist.add_song(parsed_song, allow_duplicate=True)
            if not is_added:
                print(f"Warning - Not addding song: {parsed_song.name}")
        if tracks["next"]:
            tracks = sp.next(tracks)
        else:
            tracks = None

    return all_songs


def main():

    playlist_id = "2snz2HZz2ZWa6U3JK1hF19"

    playlist = parse_playlist(playlist_id, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET)
    return


if __name__ == "__main__":
    main()
