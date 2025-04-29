# playlist_sync_diff/main.py
import json
from difflib import unified_diff
from pathlib import Path

# from deezer_client import get_deezer_playlist_tracks
import spotify_handler
from config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
from utils import ServiceName


def get_file_location(service_name, playlist_name):
    snapshot_dir = Path("snapshots") / service_name
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    file_path = snapshot_dir / f"{playlist_name}.json"
    return file_path


def save_snapshot(service_name, playlist_name, tracks):
    file_path = get_file_location(service_name, playlist_name)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(tracks, f, indent=2)
    return


def load_snapshot(service_name, playlist_name):
    file_path = get_file_location(service_name, playlist_name)
    if not file_path.exists():
        return []
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


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

    spotify_tracks = spotify_handler.load_playlist(
        playlist_id_spotify, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
    )
    # deezer_tracks = get_deezer_playlist_tracks(playlist_id_deezer)

    sp_path = save_snapshot("spotify", playlist_name, spotify_tracks)
    # dz_path = save_snapshot("deezer", playlist_name, deezer_tracks)

    old_spotify = load_snapshot(sp_path)
    # old_deezer = load_snapshot(dz_path)

    # print("--- Spotify vs Deezer ---")
    # diff = diff_playlists(old_spotify, old_deezer)
    # print("\n".join(diff))


if __name__ == "__main__":
    main()
