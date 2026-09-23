from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import platformdirs

from .syncer import Playlist, Song

_TIMESTAMP_FMT = "%Y%m%dT%H%M%S%f"


def _data_dir() -> Path:
    """Root directory for state/snapshots.

    Defaults to the OS-appropriate XDG-ish data dir (via platformdirs);
    override with SYNCZIK_DATA_DIR (e.g. to keep everything next to the repo,
    share it via a synced folder, or — in tests — isolate it from the real
    one).
    """
    override = os.environ.get("SYNCZIK_DATA_DIR")
    if override:
        return Path(override)
    return Path(platformdirs.user_data_dir("SyncZik", appauthor=False))


def migrate_legacy_storage() -> bool:
    """Copy pre-Phase-5 CWD-relative state/snapshots into the data dir, once.

    Only copies (never deletes or overwrites) — safe to call on every
    startup. Only acts when the new location doesn't already have that
    directory, so it never clobbers data already migrated or created fresh
    at the new location. Returns True if anything was copied.
    """
    data_dir = _data_dir()
    migrated = False
    for name in ("state", "snapshots"):
        legacy = Path(name)
        new = data_dir / name
        if legacy.is_dir() and any(legacy.iterdir()) and not new.exists():
            new.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(legacy, new)
            migrated = True
    return migrated


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
# Raw API snapshots (merge base) — versioned history
#
# Each save_snapshot() call appends a new timestamped file under
# snapshots/{service}/{id}/ rather than overwriting a single file, so
# playlist_git.log()/revert() can look back through past sync/clone points.
# load_snapshot() always reads the latest version, falling back to the old
# pre-history flat-file layout for installs that predate this.
# ---------------------------------------------------------------------------

@dataclass
class SnapshotVersion:
    """One recorded snapshot of a playlist's songs at a point in time."""
    timestamp: datetime
    songs: list[Song]


def _snapshot_version_dir(service: str, playlist_id: str) -> Path:
    p = _data_dir() / "snapshots" / service / playlist_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def _legacy_snapshot_path(service: str, playlist_id: str) -> Path:
    return _data_dir() / "snapshots" / service / f"{playlist_id}.json"


def save_snapshot(service: str, playlist_id: str, songs: list[Song]) -> None:
    version_dir = _snapshot_version_dir(service, playlist_id)
    timestamp = datetime.now(tz=timezone.utc).strftime(_TIMESTAMP_FMT)
    _atomic_write_json(version_dir / f"{timestamp}.json", [s.to_dict() for s in songs])


def _latest_version_file(service: str, playlist_id: str) -> Optional[Path]:
    version_dir = _data_dir() / "snapshots" / service / playlist_id
    if not version_dir.exists():
        return None
    files = sorted(version_dir.glob("*.json"))
    return files[-1] if files else None


def load_snapshot(service: str, playlist_id: str) -> list[Song]:
    latest = _latest_version_file(service, playlist_id)
    if latest is not None:
        with open(latest, "r", encoding="utf-8") as f:
            return [Song.from_dict(d) for d in json.load(f)]

    legacy = _legacy_snapshot_path(service, playlist_id)
    if legacy.exists():
        with open(legacy, "r", encoding="utf-8") as f:
            return [Song.from_dict(d) for d in json.load(f)]
    return []


def list_snapshot_versions(service: str, playlist_id: str) -> list[SnapshotVersion]:
    """Return every recorded snapshot version for a playlist, newest first."""
    version_dir = _data_dir() / "snapshots" / service / playlist_id
    if not version_dir.exists():
        return []
    versions = []
    for f in sorted(version_dir.glob("*.json"), reverse=True):
        timestamp = datetime.strptime(f.stem, _TIMESTAMP_FMT).replace(tzinfo=timezone.utc)
        with open(f, "r", encoding="utf-8") as fh:
            songs = [Song.from_dict(d) for d in json.load(fh)]
        versions.append(SnapshotVersion(timestamp=timestamp, songs=songs))
    return versions


# ---------------------------------------------------------------------------
# Local playlist state (working tree)
# ---------------------------------------------------------------------------

def _state_path(service: str, playlist_id: str) -> Path:
    p = _data_dir() / "state" / service
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


def delete_playlist(service: str, playlist_id: str) -> None:
    """Untrack a playlist locally: remove its working-tree state and snapshot history.

    Does not touch the playlist on the remote service.
    """
    state_path = _state_path(service, playlist_id)
    if state_path.exists():
        state_path.unlink()

    legacy_snapshot = _legacy_snapshot_path(service, playlist_id)
    if legacy_snapshot.exists():
        legacy_snapshot.unlink()

    version_dir = _data_dir() / "snapshots" / service / playlist_id
    if version_dir.exists():
        shutil.rmtree(version_dir)


def list_playlists() -> list[Playlist]:
    playlists: list[Playlist] = []
    state_dir = _data_dir() / "state"
    if not state_dir.exists():
        return playlists
    for service_dir in state_dir.iterdir():
        if not service_dir.is_dir():
            continue
        for state_file in service_dir.glob("*.json"):
            with open(state_file, "r", encoding="utf-8") as f:
                playlists.append(Playlist.from_dict(json.load(f)))
    return playlists
