"""Git-like operations on playlists: diff, cherry-pick, fork-from-user, log, revert."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .providers.base import ServiceProvider
from .snapshot_handler import list_snapshot_versions, save_playlist_state, save_snapshot
from .sync_engine import clone
from .syncer import Playlist, Song


@dataclass
class PlaylistDiff:
    """Symmetric difference between two playlists."""
    only_in_left: list[Song] = field(default_factory=list)
    only_in_right: list[Song] = field(default_factory=list)
    in_both: list[Song] = field(default_factory=list)

    def is_identical(self) -> bool:
        return not self.only_in_left and not self.only_in_right


def diff(left: Playlist, right: Playlist) -> PlaylistDiff:
    """Compare two playlists by song ID. Returns which songs are exclusive to each."""
    left_by_id = {s.id: s for s in left.songs}
    right_by_id = {s.id: s for s in right.songs}
    left_ids = set(left_by_id)
    right_ids = set(right_by_id)

    return PlaylistDiff(
        only_in_left=[left_by_id[sid] for sid in left_ids - right_ids],
        only_in_right=[right_by_id[sid] for sid in right_ids - left_ids],
        in_both=[left_by_id[sid] for sid in left_ids & right_ids],
    )


def cherry_pick(
    target: Playlist,
    songs: list[Song],
) -> list[Song]:
    """Add specific songs from any source into target (locally staged).

    Skips songs already present. Returns the list of songs actually added.
    Call sync_engine.sync() afterwards to push the additions to the remote.
    """
    added: list[Song] = []
    for song in songs:
        if target.add_song(song):
            added.append(song)
    if added:
        save_playlist_state(target)
    return added


def fork_from_user(
    provider: ServiceProvider,
    user_id: str,
    source_playlist_id: str,
    new_name: str,
    description: str = "",
) -> Playlist:
    """Fork any playlist (including another user's) into your own library.

    Thin wrapper around clone() that makes the intent explicit.
    The source playlist need not be owned by user_id.
    """
    return clone(provider, user_id, source_playlist_id, new_name, description)


def songs_in_playlist(
    provider: ServiceProvider,
    playlist_id: str,
) -> list[Song]:
    """Fetch live songs from a remote playlist without cloning it locally.

    Useful for browsing another user's playlist before deciding what to cherry-pick.
    """
    return provider.fetch_songs(playlist_id)


@dataclass
class LogEntry:
    """What changed at one recorded snapshot point (each clone/sync creates one)."""
    timestamp: datetime
    added: list[Song] = field(default_factory=list)
    removed: list[Song] = field(default_factory=list)
    total_songs: int = 0


def log(service: str, playlist_id: str) -> list[LogEntry]:
    """Git-log-style view of every recorded clone/sync point, newest first.

    Derived from the versioned snapshot history (snapshot_handler.py) rather
    than a separate event log, so it always reflects exactly what baseline
    was recorded at each point — no separate log file to keep in sync.
    """
    versions = list(reversed(list_snapshot_versions(service, playlist_id)))  # oldest first
    entries: list[LogEntry] = []
    previous_by_id: dict[str, Song] = {}
    for version in versions:
        current_by_id = {s.id: s for s in version.songs}
        added = [current_by_id[sid] for sid in current_by_id.keys() - previous_by_id.keys()]
        removed = [previous_by_id[sid] for sid in previous_by_id.keys() - current_by_id.keys()]
        entries.append(LogEntry(
            timestamp=version.timestamp,
            added=added,
            removed=removed,
            total_songs=len(version.songs),
        ))
        previous_by_id = current_by_id
    entries.reverse()  # newest first
    return entries


def revert(playlist: Playlist, timestamp: datetime) -> Playlist:
    """Restore local working-tree state to a previously recorded snapshot version.

    Local-only — the remote is never touched here. The reverted content
    becomes the new "local" side of the next sync(): songs added/removed on
    the remote since that point are still pulled in normally, and whatever
    the revert changed relative to the current baseline is pushed as a local
    change, exactly like reverting a file and committing in git.
    """
    versions = list_snapshot_versions(playlist.service, playlist.service_id)
    match = next((v for v in versions if v.timestamp == timestamp), None)
    if match is None:
        raise ValueError(f"No recorded snapshot at {timestamp} for this playlist.")
    playlist.songs = list(match.songs)
    save_playlist_state(playlist)
    return playlist
