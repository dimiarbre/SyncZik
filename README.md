# SyncZik

**Git for playlists** — fork, sync, and manage playlists across streaming platforms.

## What it does

SyncZik brings a git-like workflow to your music playlists:

- **Clone** a playlist from Spotify (or Deezer) and get an independent copy you can modify
- **Sync** bidirectionally: changes made on Spotify are pulled into your local copy; local edits (add/remove songs) are pushed back to Spotify
- **Track history** using local snapshots as merge bases — the same idea as a git remote
- **Cross-platform** (coming soon): clone a Spotify playlist and sync it to Deezer, or vice versa

### Example workflow

```
# You have playlist A on Spotify with 50 songs.
# Clone it → Spotify playlist B is created, SyncZik tracks it locally.
# You add 5 songs to B locally.
# The owner of A adds 3 new songs.
# You run Sync → your 5 songs are pushed to B on Spotify,
#                 the 3 new songs from A are pulled into B.
```

## Supported platforms

| Platform | Read | Write | Clone source | Clone target |
|----------|------|-------|-------------|--------------|
| Spotify  | ✓    | ✓     | ✓           | ✓            |
| Deezer   | planned | planned | planned | planned   |

## Setup

### 1. Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2. Spotify credentials

Create an app at [developer.spotify.com](https://developer.spotify.com), add `http://localhost:8888/callback` as a redirect URI, then fill in `.env`:

```env
SPOTIFY_CLIENT_ID=your_client_id
SPOTIFY_CLIENT_SECRET=your_client_secret
SPOTIFY_REDIRECT_URI=http://localhost:8888/callback
SPOTIFY_USER_ID=your_spotify_username
```

### 3. Run

```bash
syncZik
```

A browser window opens for Spotify login on first run. The TUI launches after authentication.

## TUI usage

```
┌──────────────────────────────────────────────────────────────────┐
│  SyncZik                                                         │
├──────────────────────────┬───────────────────────────────────────┤
│ Playlists                │ Songs                                 │
│                          │                                       │
│  My Playlists            │  Title              Artist  Status    │
│  ├── Playlist A (source) │  Track 1            Artist A          │
│  │   └── My Clone        │  Track 2            Artist B  [local] │
│  └── Another playlist    │  Track 3            Artist C          │
│                          │                                       │
├──────────────────────────┴───────────────────────────────────────┤
│[Load [L]]  [Clone [C]]  [Sync [S]]  [Add song [A]]  [Remove [D]] │
└──────────────────────────────────────────────────────────────────┘
```

### Actions

| Key / Button | Action |
|---|---|
| `L` | **Load** — paste a Spotify playlist URL or ID to import it locally |
| `C` | **Clone** — fork the selected playlist; creates a new Spotify playlist and starts tracking it |
| `S` | **Sync** — bidirectional merge: pushes local changes to Spotify, pulls remote changes down |
| `A` | **Add song** — search Spotify and stage a song (appears as `[local]` until next Sync) |
| `D` | **Remove** — stage the selected song for removal (applied on next Sync) |
| `Q` | Quit |

### Typical workflow

1. Press `L`, paste a Spotify playlist URL → the playlist and its songs appear.
2. Press `C`, enter a name → SyncZik creates a copy on Spotify and tracks it locally.
3. Select the clone, press `A` to add songs or `D` to remove them — changes are **staged** locally (shown with `[local]`).
4. Press `S` to sync: staged additions/removals are pushed to Spotify, and any changes made directly on Spotify are pulled down. If songs were removed on Spotify while you still have them locally, a dialog lets you decide what to keep.

## Architecture

```
src/SyncZik/
├── providers/
│   ├── base.py        # ServiceProvider ABC — unified API for all platforms
│   ├── spotify.py     # SpotifyProvider implementation
│   └── deezer.py      # DeezerProvider (stub, coming soon)
├── syncer.py          # Playlist, Song, Artist data models
├── snapshot_handler.py# Local state and baseline snapshot persistence
├── sync_engine.py     # Clone / sync (merge) logic
├── auth.py            # Spotify OAuth
└── tui.py             # Textual terminal UI
```

### Provider interface

Every streaming service implements `ServiceProvider`:

```python
class ServiceProvider(ABC):
    def get_playlist(self, playlist_id: str) -> Playlist: ...
    def fetch_songs(self, playlist_id: str) -> list[Song]: ...
    def search_tracks(self, query: str, limit: int = 10) -> list[Song]: ...
    def create_playlist(self, user_id: str, name: str, description: str = "") -> str: ...
    def add_songs(self, playlist_id: str, songs: list[Song]) -> None: ...
    def remove_songs(self, playlist_id: str, songs: list[Song]) -> None: ...
```

### Sync model

```
Baseline snapshot  ←  last common state (saved locally after each sync)
       │
       ├── Remote diff  (what changed on Spotify since baseline)
       └── Local diff   (what you changed locally since baseline)
              ↓
         Merge result → applied to both local state and Spotify
```

## Local data

| Path | Contents |
|------|----------|
| `state/{service}/{id}.json` | Local playlist state (working tree) |
| `snapshots/{service}/{id}.json` | Baseline snapshot (merge base) |
| `.spotify_cache` | Cached OAuth token |
