import spotipy
from config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
from spotipy.oauth2 import SpotifyClientCredentials
from syncer import Artist, Playlist, Song


def parse_artists(artists_json: list) -> list[Artist]:
    return [Artist(name=a["name"], id=a["id"]) for a in artists_json]


def parse_song(item: dict) -> Song:
    track = item["track"]
    return Song(
        name=track["name"],
        artists=parse_artists(track["artists"]),
        uri=track["uri"],
        id=track["id"],
    )


def parse_playlist(playlist_id: str, sp: spotipy.Spotify) -> Playlist:
    raw = sp.playlist(playlist_id)

    playlist = Playlist(
        service="spotify",
        service_id=playlist_id,
        name=raw["name"],
        owner=raw["owner"]["display_name"],
    )

    tracks = raw["tracks"]
    while tracks:
        for item in tracks["items"]:
            if item["track"] is None:
                continue
            playlist.add_song(parse_song(item), allow_duplicate=False)
        tracks = sp.next(tracks) if tracks["next"] else None

    return playlist


def build_client_credentials_client() -> spotipy.Spotify:
    auth_manager = SpotifyClientCredentials(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET)
    return spotipy.Spotify(auth_manager=auth_manager)
