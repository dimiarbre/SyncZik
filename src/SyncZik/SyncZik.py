# playlist_sync_diff/main.py
import json
from difflib import unified_diff

# from deezer_client import get_deezer_playlist_tracks
import spotify_handler
from config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
from snapshot_handler import get_file_location, load_snapshot, save_snapshot
from utils import ServiceName


def diff_playlists(old, new):
    old_lines = [f"{t['artist']} - {t['title']}" for t in old]
    new_lines = [f"{t['artist']} - {t['title']}" for t in new]
    diff = unified_diff(
        old_lines, new_lines, fromfile="before", tofile="after", lineterm=""
    )
    return list(diff)


def main():

    playlist_name = "KEMIST Stream"
    playlist_id_spotify = "2snz2HZz2ZWa6U3JK1hF19"
    service = "spotify"
    sp_path = get_file_location(service, playlist_name)

    # spotify_tracks = spotify_handler.load_playlist(
    #     playlist_id_spotify, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
    # )
    # save_snapshot("spotify", playlist_name, spotify_tracks)

    # deezer_tracks = get_deezer_playlist_tracks(playlist_id_deezer)
    # save_snapshot("deezer", playlist_name, deezer_tracks)

    old_spotify = load_snapshot(sp_path, playlist_name)
    # old_deezer = load_snapshot(dz_path)

    # print("--- Spotify vs Deezer ---")
    # diff = diff_playlists(old_spotify, old_deezer)
    # print("\n".join(diff))


if __name__ == "__main__":
    main()
