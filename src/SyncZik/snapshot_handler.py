import json
from pathlib import Path


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
