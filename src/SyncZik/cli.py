"""Headless CLI: clone/sync/cherry-pick/export without the TUI.

Reuses sync_engine.py/playlist_git.py directly so scripting and cron jobs
don't need an interactive terminal. `run_cli()` returns None when the user
passed no subcommand (the caller should launch the TUI in that case), or an
exit code once a subcommand has run.
"""
from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from .auth import get_deezer_client, get_spotify_client
from .config import SPOTIFY_USER_ID
from .cross_platform import execute_export, plan_export
from .logging_setup import setup_logging
from .playlist_git import cherry_pick, songs_in_playlist
from .providers.base import ServiceProvider
from .providers.deezer import DeezerProvider
from .providers.spotify import SpotifyProvider
from .snapshot_handler import list_playlists
from .sync_engine import clone as clone_playlist
from .sync_engine import sync as sync_playlist
from .syncer import Playlist
from .utils import ServiceName


def _build_provider(service: ServiceName) -> ServiceProvider:
    if service == "deezer":
        return DeezerProvider(get_deezer_client())
    return SpotifyProvider(get_spotify_client())


def _extract_id(raw: str) -> str:
    """Accept either a bare ID or a full playlist URL."""
    raw = raw.strip()
    if "/" in raw:
        raw = raw.rstrip("/").split("/")[-1].split("?")[0]
    return raw


def _resolve_user_id(provider: ServiceProvider) -> str:
    if provider.service_name == "spotify":
        if not SPOTIFY_USER_ID:
            raise SystemExit("SPOTIFY_USER_ID not set in .env — see README's Setup section.")
        return SPOTIFY_USER_ID
    return ""


def _find_tracked_playlist(playlist_id: str, service: Optional[ServiceName]) -> Playlist:
    matches = [
        p for p in list_playlists()
        if p.service_id == playlist_id and (service is None or p.service == service)
    ]
    if not matches:
        where = f" on {service}" if service else ""
        raise SystemExit(f'No tracked playlist found with id "{playlist_id}"{where}.')
    if len(matches) > 1:
        services = ", ".join(p.service for p in matches)
        raise SystemExit(
            f'Ambiguous playlist id "{playlist_id}" is tracked on multiple services '
            f"({services}) — pass --service to disambiguate."
        )
    return matches[0]


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_clone(args: argparse.Namespace) -> int:
    provider = _build_provider(args.service)
    user_id = _resolve_user_id(provider)
    source_id = _extract_id(args.source)
    playlist = clone_playlist(provider, user_id, source_id, args.name, description=args.description)
    print(f'Cloned "{playlist.name}" ({len(playlist.songs)} songs) -> {playlist.service}:{playlist.service_id}')
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    if args.all:
        targets = list_playlists()
        if not targets:
            print("No tracked playlists to sync.")
            return 0
    else:
        if not args.playlist_id:
            raise SystemExit("Pass a playlist id, or --all to sync every tracked playlist.")
        targets = [_find_tracked_playlist(args.playlist_id, args.service)]

    exit_code = 0
    for playlist in targets:
        provider = _build_provider(playlist.service)
        try:
            result = sync_playlist(provider, playlist)
        except Exception as e:
            print(f'"{playlist.name}": sync failed: {e}', file=sys.stderr)
            exit_code = 1
            continue

        if result.errors:
            for err in result.errors:
                print(f'"{playlist.name}": {err}', file=sys.stderr)
            exit_code = 1

        parts = []
        if result.pushed_to_remote:
            parts.append(f"pushed {len(result.pushed_to_remote)}")
        if result.removed_from_remote:
            parts.append(f"removed {len(result.removed_from_remote)}")
        if result.added_from_remote:
            parts.append(f"pulled {len(result.added_from_remote)}")
        if result.removed_from_remote_pending:
            parts.append(
                f"{len(result.removed_from_remote_pending)} pending remote removal(s) "
                "(resolve with the TUI)"
            )
        print(f'"{playlist.name}": {", ".join(parts) if parts else "up to date"}')
    return exit_code


def cmd_cherry_pick(args: argparse.Namespace) -> int:
    target = _find_tracked_playlist(args.target, args.service)
    provider = _build_provider(target.service)
    source_id = _extract_id(args.source)
    songs = songs_in_playlist(provider, source_id)
    added = cherry_pick(target, songs)
    print(f'Cherry-picked {len(added)} song(s) into "{target.name}" (staged — run sync to push)')
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    source = _find_tracked_playlist(args.source, args.service)
    target_provider = _build_provider(args.target_service)
    user_id = _resolve_user_id(target_provider)
    plan = plan_export(source.songs, target_provider)
    songs = [target for _, target in plan.auto_resolved]
    playlist_id = execute_export(
        target_provider, user_id, args.name, songs,
        description=f"Exported from {source.name} — managed by SyncZik",
    )
    skipped = plan.total() - len(songs)
    suffix = f", {skipped} skipped — conflicts aren't resolved in the CLI, use the TUI)" if skipped else ")"
    print(f'Exported "{args.name}" ({len(songs)} songs{suffix}')
    print(f"New playlist id: {playlist_id}")
    return 0


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="syncZik", description="Git for playlists.")
    parser.add_argument(
        "--verbose", action="store_true", help="Enable debug-level logging to the log file."
    )
    subparsers = parser.add_subparsers(dest="command")

    clone_p = subparsers.add_parser("clone", help="Fork a playlist and track it locally.")
    clone_p.add_argument("source", help="Source playlist URL or ID.")
    clone_p.add_argument("name", help="Name for the new playlist.")
    clone_p.add_argument("--service", choices=["spotify", "deezer"], default="spotify")
    clone_p.add_argument("--description", default="")
    clone_p.set_defaults(func=cmd_clone)

    sync_p = subparsers.add_parser("sync", help="Bidirectionally sync one or all tracked playlists.")
    sync_p.add_argument("playlist_id", nargs="?", help="Tracked playlist id to sync.")
    sync_p.add_argument(
        "--service", choices=["spotify", "deezer"], default=None,
        help="Disambiguate playlist_id if it's tracked on more than one service.",
    )
    sync_p.add_argument("--all", action="store_true", help="Sync every tracked playlist.")
    sync_p.set_defaults(func=cmd_sync)

    pick_p = subparsers.add_parser(
        "cherry-pick", help="Pull every song not already present from a source playlist into a tracked one."
    )
    pick_p.add_argument("target", help="Tracked target playlist id.")
    pick_p.add_argument("source", help="Source playlist URL or ID to pull songs from.")
    pick_p.add_argument(
        "--service", choices=["spotify", "deezer"], default=None,
        help="Disambiguate target if it's tracked on more than one service.",
    )
    pick_p.set_defaults(func=cmd_cherry_pick)

    export_p = subparsers.add_parser("export", help="Export a tracked playlist to another platform.")
    export_p.add_argument("source", help="Tracked source playlist id.")
    export_p.add_argument("target_service", choices=["spotify", "deezer"], help="Platform to export to.")
    export_p.add_argument("name", help="Name for the exported playlist.")
    export_p.add_argument(
        "--service", choices=["spotify", "deezer"], default=None,
        help="Disambiguate source if it's tracked on more than one service.",
    )
    export_p.set_defaults(func=cmd_export)

    return parser


def run_cli(argv: Optional[Sequence[str]] = None) -> Optional[int]:
    """Parse argv and dispatch a subcommand.

    Returns None if no subcommand was given (caller should launch the TUI
    instead), otherwise the process exit code.
    """
    args = build_parser().parse_args(argv)
    setup_logging(verbose=args.verbose)
    if not getattr(args, "command", None):
        return None
    try:
        return args.func(args)
    except SystemExit as e:
        print(f"Error: {e.code}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
