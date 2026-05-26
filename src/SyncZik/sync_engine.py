from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .providers.base import ServiceProvider
from .snapshot_handler import (
    list_playlists,
    load_snapshot,
    load_playlist_state,
    save_playlist_state,
    save_snapshot,
)
from .syncer import Playlist, Song


@dataclass
class MergeResult:
    """Summary of what happened during a sync operation."""
    added_from_remote: list[Song] = field(default_factory=list)
    removed_from_remote_pending: list[Song] = field(default_factory=list)
    pushed_to_remote: list[Song] = field(default_factory=list)
    removed_from_remote: list[Song] = field(default_factory=list)

    def is_clean(self) -> bool:
        return not (
            self.added_from_remote
            or self.removed_from_remote_pending
            or self.pushed_to_remote
            or self.removed_from_remote
        )


def _song_set(songs: list[Song]) -> set[str]:
    """Return a set of song IDs for fast membership tests."""
    return {s.id for s in songs}


def _songs_by_id(songs: list[Song]) -> dict[str, Song]:
    return {s.id: s for s in songs}


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------

def clone(
    provider: ServiceProvider,
    user_id: str,
    source_playlist_id: str,
    new_name: str,
    description: str = "",
) -> Playlist:
    """Fork a playlist: fetch source, create a new remote playlist, save local state."""
    source = provider.get_playlist(source_playlist_id)

    new_service_id = provider.create_playlist(user_id, new_name, description)
    provider.add_songs(new_service_id, source.songs)

    clone_playlist = Playlist(
        service=provider.service_name,
        service_id=new_service_id,
        name=new_name,
        owner=user_id,
        parent_id=source_playlist_id,
        parent_service=provider.service_name,
        last_synced=datetime.now(tz=timezone.utc),
    )
    clone_playlist.songs = list(source.songs)

    save_snapshot(provider.service_name, new_service_id, source.songs)
    save_playlist_state(clone_playlist)
    return clone_playlist


def sync(provider: ServiceProvider, playlist: Playlist) -> MergeResult:
    """Bidirectional sync between local state and the remote playlist.

    Uses the saved baseline snapshot as the merge base:
      remote diff  = what changed on the service since last sync
      local diff   = what the user changed locally since last sync
    Both diffs are merged and applied; conflicts are surfaced in MergeResult.
    Staged removals (remove_song) are applied to the remote here.
    """
    result = MergeResult()

    remote_songs = provider.fetch_songs(playlist.service_id)
    baseline_songs = load_snapshot(playlist.service, playlist.service_id)
    local_songs = playlist.songs

    remote_ids = _song_set(remote_songs)
    baseline_ids = _song_set(baseline_songs)
    local_ids = _song_set(local_songs)

    remote_by_id = _songs_by_id(remote_songs)
    baseline_by_id = _songs_by_id(baseline_songs)

    remote_added_ids = remote_ids - baseline_ids
    remote_removed_ids = baseline_ids - remote_ids
    local_added_ids = local_ids - baseline_ids
    local_removed_ids = baseline_ids - local_ids

    # --- Remote additions → pull into local ---
    for sid in remote_added_ids - local_removed_ids:
        song = remote_by_id[sid]
        playlist.add_song(song)
        result.added_from_remote.append(song)

    # --- Remote removals not also removed locally → prompt user ---
    for sid in remote_removed_ids - local_removed_ids:
        result.removed_from_remote_pending.append(baseline_by_id[sid])

    # --- Local additions → push to remote ---
    to_push = [
        _songs_by_id(local_songs)[sid]
        for sid in local_added_ids - remote_added_ids
    ]
    if to_push:
        provider.add_songs(playlist.service_id, to_push)
        result.pushed_to_remote.extend(to_push)

    # --- Local removals → remove from remote ---
    to_remove_remote = [
        baseline_by_id[sid]
        for sid in local_removed_ids - remote_removed_ids
        if sid in baseline_by_id
    ]
    if to_remove_remote:
        provider.remove_songs(playlist.service_id, to_remove_remote)
        result.removed_from_remote.extend(to_remove_remote)

    # Persist updated state and new baseline (remote is now the new truth)
    new_baseline = provider.fetch_songs(playlist.service_id)
    playlist.last_synced = datetime.now(tz=timezone.utc)
    save_snapshot(playlist.service, playlist.service_id, new_baseline)
    playlist.songs = new_baseline
    save_playlist_state(playlist)

    return result


def apply_remote_removal(
    provider: ServiceProvider,
    playlist: Playlist,
    songs: list[Song],
) -> None:
    """Remove songs that were deleted on the remote and the user confirmed to drop locally.

    Called after the user responds to MergeResult.removed_from_remote_pending.
    """
    for song in songs:
        playlist.remove_song(song)

    # Persist — next sync will pick up the final remote state
    save_playlist_state(playlist)


def add_song(playlist: Playlist, song: Song) -> bool:
    """Stage a song addition locally. Call sync() to push it to the remote."""
    added = playlist.add_song(song)
    if added:
        save_playlist_state(playlist)
    return added


def remove_song(playlist: Playlist, song: Song) -> bool:
    """Stage a song removal locally. Call sync() to apply it on the remote."""
    removed = playlist.remove_song(song)
    if removed:
        save_playlist_state(playlist)
    return removed
