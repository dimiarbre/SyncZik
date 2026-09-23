# Changelog

Notable changes to SyncZik, newest first. No formal version releases yet
(everything below has landed on `main`), so entries are dated instead.

## 2026-09-23 — Project maturity

- `pyproject.toml` replaces `setup.py`/`setup.cfg`/`mypy.ini`; `ruff` (lint +
  format) added and made blocking in CI alongside `mypy` (previously
  advisory-only); CI runs a Python 3.12/3.13 matrix with coverage reporting.
- `state`/`snapshots` moved from CWD-relative paths to an XDG-compliant data
  directory (via `platformdirs`, overridable with `SYNCZIK_DATA_DIR`), with
  a one-time, copy-only migration for existing installs.
- `.pre-commit-config.yaml`, `CHANGELOG.md`, `SECURITY.md`, issue/PR
  templates, README badges and a real screenshot, troubleshooting/FAQ
  section.

## 2026-09-23 — Headless CLI

- `syncZik clone|sync|cherry-pick|export` subcommands reuse the same
  `sync_engine.py`/`playlist_git.py` as the TUI, for scripting/cron use;
  `sync --all` syncs every tracked playlist in one invocation.
- Rotating debug log file shared by the TUI and CLI (`--verbose` for debug
  level), instead of only ephemeral toasts/stderr.
- Spotify credential validation at the point of use with an actionable
  message; `.env.example`.

## 2026-09-23 — Playlist history

- Every Clone/Sync now records a versioned snapshot instead of overwriting
  one; `playlist_git.log()`/`revert()` and a TUI History screen (`H`) show
  what changed at each point and can revert local state to any of them.
- Local `Rename` (`R`) and `Untrack` (`X`, with confirmation) for tracked
  playlists.

## 2026-09-23 — TUI responsiveness

- Load/Clone/Sync/Search/Export/Cherry-pick run off the UI thread with a
  loading indicator instead of freezing the app.
- `playlist_git.diff()` wired into the TUI (`V`); per-song sync
  pending-removal decisions instead of only "remove all"/"keep all";
  one-level undo (`U`); a help screen (`?`); escape-to-cancel on every
  modal; a real fix for cherry-pick's non-functional "Space to toggle"
  hint; first-run onboarding hint.

## 2026-09-23 — Reliability foundation

- Retry/backoff with `Retry-After` support on rate limits and transient
  errors; `SyncZikError` translation (`ProviderAuthError`,
  `ProviderRateLimitError`, `ProviderNotFoundError`) at the provider
  boundary instead of raw library exceptions.
- Atomic state/snapshot writes (temp file + rename); a sync that fails
  partway through a push/removal reports it instead of silently marking
  the playlist as up to date.
- ISRC-first cross-platform matching with a duration tiebreak; new
  `Song.album`/`duration_ms`/`isrc`/`added_at` fields; order-preserving
  remote pulls.

## 2026-09-23 — Deezer as home provider

- Choose Spotify or Deezer at TUI startup; Load/Clone/Sync/Search all work
  against whichever is active (previously Deezer was export-only).
- Repo hygiene: MIT license, CI (`pytest` + `mypy`), packaging metadata.

## 2026-09-22 — Deezer write support

- `DeezerProvider.create_playlist`/`add_songs`/`remove_songs`; the export
  flow can target Deezer.

## 2026-09-22 — Cross-platform export

- `cross_platform.py`: `plan_export`/`execute_export` with
  exact/ambiguous/not-found conflict classification; a TUI conflict
  resolver screen; `playlist_git.py`: `diff`, `cherry_pick`,
  `fork_from_user`, `songs_in_playlist`.

## 2026-05-26 — Initial TUI

- Textual two-panel layout (playlist tree + song table), search modal,
  sync result modal, Spotify OAuth, bidirectional sync with a merge-base
  snapshot.
