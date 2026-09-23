import json
import os
import tempfile
from pathlib import Path
from typing import Optional

from .syncer import Playlist, Song


def _atomic_write_json(path: Path, data: object) -> None:
    """Write JSON atomically: dump to a sibling temp file, then rename into place.

    Avoids leaving a truncated/corrupted file if the process crashes or is
    killed mid-write.
    """
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, path)
    except BaseException:
        os.unlink(tmp_path)
        raise


# ---------------------------------------------------------------------------
# Raw API snapshots (merge base)
# ---------------------------------------------------------------------------

def _snapshot_path(service: str, playlist_id: str) -> Path:
    p = Path("snapshots") / service
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{playlist_id}.json"


def save_snapshot(service: str, playlist_id: str, songs: list[Song]) -> None:
    path = _snapshot_path(service, playlist_id)
    _atomic_write_json(path, [s.to_dict() for s in songs])


def load_snapshot(service: str, playlist_id: str) -> list[Song]:
    path = _snapshot_path(service, playlist_id)
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [Song.from_dict(d) for d in json.load(f)]


# ---------------------------------------------------------------------------
# Local playlist state (working tree)
# ---------------------------------------------------------------------------

def _state_path(service: str, playlist_id: str) -> Path:
    p = Path("state") / service
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{playlist_id}.json"


def save_playlist_state(playlist: Playlist) -> None:
    path = _state_path(playlist.service, playlist.service_id)
    _atomic_write_json(path, playlist.to_dict())


def load_playlist_state(service: str, playlist_id: str) -> Optional[Playlist]:
    path = _state_path(service, playlist_id)
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return Playlist.from_dict(json.load(f))


def list_playlists() -> list[Playlist]:
    playlists: list[Playlist] = []
    state_dir = Path("state")
    if not state_dir.exists():
        return playlists
    for service_dir in state_dir.iterdir():
        if not service_dir.is_dir():
            continue
        for state_file in service_dir.glob("*.json"):
            with open(state_file, "r", encoding="utf-8") as f:
                playlists.append(Playlist.from_dict(json.load(f)))
    return playlists
