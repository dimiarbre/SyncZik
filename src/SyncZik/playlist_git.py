"""Git-like operations on playlists: diff, cherry-pick, fork-from-user."""
from __future__ import annotations

from dataclasses import dataclass, field

from .providers.base import ServiceProvider
from .snapshot_handler import save_playlist_state, save_snapshot
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
