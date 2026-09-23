from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Static,
    Tree,
)
from textual.widgets.tree import TreeNode

from .auth import get_deezer_client, get_spotify_client
from .config import SPOTIFY_USER_ID
from .cross_platform import ExportPlan, MatchKind, SongConflict, execute_export, plan_export
from .playlist_git import cherry_pick, diff, fork_from_user, songs_in_playlist
from .providers.base import ServiceProvider
from .providers.deezer import DeezerProvider
from .providers.spotify import SpotifyProvider
from .utils import ServiceName
from .snapshot_handler import list_playlists, save_playlist_state
from .sync_engine import (
    MergeResult,
    add_song,
    apply_remote_removal,
    clone,
    remove_song,
    sync,
)
from .syncer import Playlist, Song


# ---------------------------------------------------------------------------
# Provider helpers
# ---------------------------------------------------------------------------

def build_provider(choice: ServiceName) -> ServiceProvider:
    """Connect to the chosen platform and wrap it as a ServiceProvider.

    Raises RuntimeError (propagated from get_deezer_client) if Deezer is
    chosen but DEEZER_ACCESS_TOKEN isn't configured.
    """
    if choice == "deezer":
        return DeezerProvider(get_deezer_client())
    return SpotifyProvider(get_spotify_client())


def resolve_clone_user_id(provider: ServiceProvider) -> str | None:
    """Return the user_id to pass to clone()/create_playlist for this provider.

    Spotify's create_playlist requires an owning user_id; Deezer's ignores it
    (the token's own account is implicit) so any placeholder is fine. Returns
    None when a required SPOTIFY_USER_ID is missing, signaling the caller to
    show an error instead of proceeding.
    """
    if provider.service_name == "spotify":
        return SPOTIFY_USER_ID or None
    return ""


# ---------------------------------------------------------------------------
# Modal screens
# ---------------------------------------------------------------------------

class InputModal(ModalScreen[str | None]):
    """Single-line text input dialog."""

    def __init__(self, title: str, placeholder: str = "") -> None:
        super().__init__()
        self._title = title
        self._placeholder = placeholder

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self._title, id="dialog-title")
            yield Input(placeholder=self._placeholder, id="dialog-input")
            with Horizontal(id="dialog-buttons"):
                yield Button("OK", variant="primary", id="ok")
                yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok":
            self.dismiss(self.query_one("#dialog-input", Input).value.strip() or None)
        else:
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)


class ProviderPickerModal(ModalScreen[ServiceName | None]):
    """Let the user pick a platform — used both for export target and home provider."""

    def __init__(self, title: str = "Export to which platform?") -> None:
        super().__init__()
        self._title = title

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self._title, id="dialog-title")
            with Horizontal(id="dialog-buttons"):
                yield Button("Spotify", variant="primary", id="spotify")
                yield Button("Deezer", id="deezer")
                yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "spotify":
            self.dismiss("spotify")
        elif event.button.id == "deezer":
            self.dismiss("deezer")
        else:
            self.dismiss(None)


class SearchModal(ModalScreen[Song | None]):
    """Search for a track and let the user pick one."""

    def __init__(self, provider: ServiceProvider) -> None:
        super().__init__()
        self._provider = provider
        self._results: list[Song] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("Search for a track", id="dialog-title")
            yield Input(placeholder="Artist or track name…", id="search-input")
            yield ListView(id="search-results")
            with Horizontal(id="dialog-buttons"):
                yield Button("Add selected", variant="primary", id="ok")
                yield Button("Cancel", id="cancel")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        query = event.value.strip()
        if not query:
            return
        self._results = self._provider.search_tracks(query, limit=8)
        lv = self.query_one("#search-results", ListView)
        lv.clear()
        for song in self._results:
            artist = song.artists[0].name if song.artists else "?"
            lv.append(ListItem(Label(f"{song.name}  —  {artist}")))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        lv = self.query_one("#search-results", ListView)
        idx = lv.index
        if idx is not None and 0 <= idx < len(self._results):
            self.dismiss(self._results[idx])
        else:
            self.dismiss(None)


class SyncResultModal(ModalScreen[list[Song]]):
    """Show sync results and let the user decide which pending removals to apply."""

    def __init__(self, result: MergeResult) -> None:
        super().__init__()
        self._result = result
        self._keep: set[str] = set()  # song IDs the user chooses to keep

    def compose(self) -> ComposeResult:
        r = self._result
        lines: list[str] = []
        if r.pushed_to_remote:
            lines.append(f"[green]Pushed {len(r.pushed_to_remote)} song(s) to remote[/green]")
        if r.removed_from_remote:
            lines.append(f"[green]Removed {len(r.removed_from_remote)} song(s) from remote[/green]")
        if r.added_from_remote:
            lines.append(f"[green]Pulled {len(r.added_from_remote)} new song(s) from remote[/green]")
        for err in r.errors:
            lines.append(f"[red]{err}[/red]")

        with Vertical(id="dialog"):
            yield Label("Sync complete", id="dialog-title")
            if lines:
                yield Static("\n".join(lines), id="sync-summary")
            if r.removed_from_remote_pending:
                yield Label(
                    f"{len(r.removed_from_remote_pending)} song(s) were removed from the remote.\n"
                    "Choose what to do with each:",
                    id="pending-label",
                )
                yield ListView(id="pending-list")
            with Horizontal(id="dialog-buttons"):
                if r.removed_from_remote_pending:
                    yield Button("Remove all pending", variant="error", id="remove-all")
                    yield Button("Keep all", id="keep-all")
                yield Button("Done", variant="primary", id="done")

    def on_mount(self) -> None:
        if self._result.removed_from_remote_pending:
            lv = self.query_one("#pending-list", ListView)
            for song in self._result.removed_from_remote_pending:
                artist = song.artists[0].name if song.artists else "?"
                lv.append(ListItem(Label(f"[yellow]?[/yellow] {song.name}  —  {artist}")))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        pending = self._result.removed_from_remote_pending
        if event.button.id == "remove-all":
            self.dismiss(list(pending))
        elif event.button.id == "keep-all":
            self.dismiss([])
        else:
            self.dismiss([])


# ---------------------------------------------------------------------------
# Cherry-pick modal
# ---------------------------------------------------------------------------

class CherryPickModal(ModalScreen[list[Song]]):
    """Browse a remote playlist, show songs not in the target, let user pick."""

    def __init__(self, provider: ServiceProvider, target: Playlist) -> None:
        super().__init__()
        self._provider = provider
        self._target = target
        self._candidates: list[Song] = []
        self._selected_ids: set[str] = set()

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("Cherry-pick from playlist", id="dialog-title")
            yield Input(placeholder="Source playlist URL or ID…", id="pick-input")
            yield Static("Enter a playlist URL then press Enter", id="pick-hint")
            yield ListView(id="pick-list")
            with Horizontal(id="dialog-buttons"):
                yield Button("Pick selected", variant="primary", id="ok")
                yield Button("Select all", id="select-all")
                yield Button("Cancel", id="cancel")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        raw = event.value.strip()
        if not raw:
            return
        if "/" in raw:
            raw = raw.rstrip("/").split("/")[-1].split("?")[0]
        try:
            remote_songs = songs_in_playlist(self._provider, raw)
        except Exception as e:
            self.query_one("#pick-hint", Static).update(f"[red]Error: {e}[/red]")
            return

        target_ids = {s.id for s in self._target.songs}
        self._candidates = [s for s in remote_songs if s.id not in target_ids]
        self._selected_ids = set()

        lv = self.query_one("#pick-list", ListView)
        lv.clear()
        hint = self.query_one("#pick-hint", Static)
        if not self._candidates:
            hint.update("[yellow]No new songs found — target already has everything.[/yellow]")
            return
        hint.update(f"{len(self._candidates)} new song(s) found. Space to toggle, then Pick.")
        for song in self._candidates:
            artist = song.artists[0].name if song.artists else "?"
            lv.append(ListItem(Label(f"[ ] {song.name}  —  {artist}")))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx = self.query_one("#pick-list", ListView).index
        if idx is None or idx >= len(self._candidates):
            return
        song = self._candidates[idx]
        label = event.item.query_one(Label)
        if song.id in self._selected_ids:
            self._selected_ids.discard(song.id)
            label.update(f"[ ] {song.name}  —  {song.artists[0].name if song.artists else '?'}")
        else:
            self._selected_ids.add(song.id)
            label.update(f"[x] {song.name}  —  {song.artists[0].name if song.artists else '?'}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss([])
        elif event.button.id == "select-all":
            lv = self.query_one("#pick-list", ListView)
            lv.clear()
            self._selected_ids = {s.id for s in self._candidates}
            for song in self._candidates:
                artist = song.artists[0].name if song.artists else "?"
                lv.append(ListItem(Label(f"[x] {song.name}  —  {artist}")))
        elif event.button.id == "ok":
            by_id = {s.id: s for s in self._candidates}
            self.dismiss([by_id[sid] for sid in self._selected_ids if sid in by_id])


# ---------------------------------------------------------------------------
# Export conflict resolver
# ---------------------------------------------------------------------------

class ExportConflictScreen(ModalScreen[list[Song]]):
    """Walk the user through resolving each cross-platform export conflict.

    For each SongConflict in the ExportPlan the user can:
      - AMBIGUOUS: pick one of the candidates, or skip
      - NOT_FOUND: search manually on the target, or skip

    Dismisses with the list of target-platform songs to include in the export.
    """

    def __init__(
        self,
        plan: ExportPlan,
        target_provider: ServiceProvider,
    ) -> None:
        super().__init__()
        self._plan = plan
        self._target_provider = target_provider
        self._resolved: list[Song] = [target for _, target in plan.auto_resolved]
        self._queue: list[SongConflict] = list(plan.conflicts)
        self._current: SongConflict | None = None
        self._search_results: list[Song] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("Export — resolve conflicts", id="dialog-title")
            yield Static("", id="conflict-info")
            yield Static("", id="conflict-counter")
            yield ListView(id="conflict-candidates")
            yield Input(placeholder="Search on target platform…", id="conflict-search")
            with Horizontal(id="dialog-buttons"):
                yield Button("Use selected", variant="primary", id="use-selected")
                yield Button("Skip song", variant="warning", id="skip")
                yield Button("Done (skip rest)", id="done")

    def on_mount(self) -> None:
        self._next_conflict()

    def _next_conflict(self) -> None:
        if not self._queue:
            self.dismiss(self._resolved)
            return
        self._current = self._queue.pop(0)
        remaining = len(self._queue) + 1
        total_conflicts = len(self._plan.conflicts)
        done = total_conflicts - remaining

        counter = self.query_one("#conflict-counter", Static)
        counter.update(f"Conflict {done + 1} of {total_conflicts}")

        src = self._current.source
        artist = src.artists[0].name if src.artists else "?"
        kind_label = "Not found on target" if self._current.kind == MatchKind.NOT_FOUND else "Ambiguous match"
        info = self.query_one("#conflict-info", Static)
        info.update(
            f"[yellow]{kind_label}[/yellow]\n"
            f"[bold]{src.name}[/bold]  —  {artist}"
        )

        lv = self.query_one("#conflict-candidates", ListView)
        lv.clear()
        self._search_results = list(self._current.candidates)
        for song in self._search_results:
            a = song.artists[0].name if song.artists else "?"
            lv.append(ListItem(Label(f"{song.name}  —  {a}")))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        query = event.value.strip()
        if not query:
            return
        try:
            results = self._target_provider.search_tracks(query, limit=8)
        except Exception as e:
            self.query_one("#conflict-info", Static).update(f"[red]Search error: {e}[/red]")
            return
        self._search_results = results
        lv = self.query_one("#conflict-candidates", ListView)
        lv.clear()
        for song in results:
            a = song.artists[0].name if song.artists else "?"
            lv.append(ListItem(Label(f"{song.name}  —  {a}")))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "use-selected":
            lv = self.query_one("#conflict-candidates", ListView)
            idx = lv.index
            if idx is not None and 0 <= idx < len(self._search_results):
                self._resolved.append(self._search_results[idx])
            self._next_conflict()
        elif event.button.id == "skip":
            self._next_conflict()
        elif event.button.id == "done":
            self.dismiss(self._resolved)


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------

SYNCZIG_CSS = """
ModalScreen {
    align: center middle;
}

#layout {
    layout: horizontal;
}

#left-panel {
    width: 35;
    border: solid $accent;
    padding: 0 1;
}

#right-panel {
    border: solid $accent;
    padding: 0 1;
}

#playlist-tree {
    height: 1fr;
}

#song-table {
    height: 1fr;
}

#action-bar {
    height: 3;
    layout: horizontal;
    padding: 0 1;
    background: $surface;
}

#action-bar Button {
    margin: 0 1;
}

#left-label, #right-label {
    background: $accent;
    color: $text;
    padding: 0 1;
    text-style: bold;
}

#dialog {
    background: $surface;
    border: solid $accent;
    padding: 1 2;
    width: 60;
    height: auto;
}

#dialog-title {
    text-style: bold;
    margin-bottom: 1;
}

#dialog-buttons {
    margin-top: 1;
    layout: horizontal;
}

#dialog-buttons Button {
    margin-right: 1;
}

#search-results {
    height: 10;
    border: solid $panel;
    margin-top: 1;
}

#pending-list {
    height: 8;
    border: solid $panel;
    margin-top: 1;
}

#sync-summary {
    margin-bottom: 1;
}

#pick-list {
    height: 12;
    border: solid $panel;
    margin-top: 1;
}

#pick-hint {
    margin-top: 1;
    color: $text-muted;
}

#conflict-info {
    margin-top: 1;
    margin-bottom: 1;
}

#conflict-counter {
    color: $text-muted;
    text-style: italic;
}

#conflict-candidates {
    height: 8;
    border: solid $panel;
    margin-top: 1;
}

#conflict-search {
    margin-top: 1;
}
"""


class SyncZikApp(App):
    CSS = SYNCZIG_CSS
    TITLE = "SyncZik"
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("c", "clone_playlist", "Clone"),
        Binding("s", "sync_playlist", "Sync"),
        Binding("a", "add_song", "Add song"),
        Binding("d", "remove_song", "Remove song"),
        Binding("l", "load_playlist", "Load playlist"),
        Binding("p", "cherry_pick", "Cherry-pick"),
        Binding("e", "export_playlist", "Export"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._provider: ServiceProvider | None = None
        self._playlists: list[Playlist] = []
        self._selected: Playlist | None = None

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="layout"):
            with Vertical(id="left-panel"):
                yield Label("Playlists", id="left-label")
                yield Tree("My Playlists", id="playlist-tree")
            with Vertical(id="right-panel"):
                yield Label("Songs", id="right-label")
                yield DataTable(id="song-table")
        with Horizontal(id="action-bar"):
            yield Button("Load [L]", id="btn-load")
            yield Button("Clone [C]", id="btn-clone")
            yield Button("Sync [S]", id="btn-sync")
            yield Button("Add song [A]", id="btn-add")
            yield Button("Remove [D]", id="btn-remove", variant="error")
            yield Button("Cherry-pick [P]", id="btn-pick", variant="success")
            yield Button("Export [E]", id="btn-export")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#song-table", DataTable)
        table.add_columns("Title", "Artist", "Status")

        tree = self.query_one("#playlist-tree", Tree)
        tree.root.expand()

        def on_choice(choice: ServiceName | None) -> None:
            try:
                self._provider = build_provider(choice or "spotify")
            except RuntimeError as e:
                self.notify(str(e), severity="error")
                self._provider = build_provider("spotify")
            self._refresh_playlist_tree()

        self.push_screen(
            ProviderPickerModal(title="Choose your home provider"), on_choice
        )

    # ------------------------------------------------------------------
    # Playlist tree
    # ------------------------------------------------------------------

    def _refresh_playlist_tree(self) -> None:
        self._playlists = list_playlists()
        tree = self.query_one("#playlist-tree", Tree)
        tree.root.remove_children()

        roots: dict[str, TreeNode] = {}
        children: list[Playlist] = []

        for p in self._playlists:
            if p.parent_id is None:
                node = tree.root.add(p.name, data=p)
                roots[p.service_id] = node
            else:
                children.append(p)

        for p in children:
            parent_node = roots.get(p.parent_id) if p.parent_id is not None else None
            if parent_node:
                parent_node.add_leaf(f"{p.name} [clone]", data=p)
            else:
                tree.root.add_leaf(f"{p.name} [clone, source gone]", data=p)

        tree.root.expand_all()

    def _show_songs(self, playlist: Playlist) -> None:
        self._selected = playlist
        table = self.query_one("#song-table", DataTable)
        table.clear()
        from .snapshot_handler import load_snapshot
        baseline_ids = {s.id for s in load_snapshot(playlist.service, playlist.service_id)}
        for song in playlist.songs:
            artist = song.artists[0].name if song.artists else "—"
            status = "" if song.id in baseline_ids else "[local]"
            table.add_row(song.name, artist, status)

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        if event.node.data and isinstance(event.node.data, Playlist):
            self._show_songs(event.node.data)

    # ------------------------------------------------------------------
    # Button → action routing
    # ------------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        mapping = {
            "btn-load": self.action_load_playlist,
            "btn-clone": self.action_clone_playlist,
            "btn-sync": self.action_sync_playlist,
            "btn-add": self.action_add_song,
            "btn-remove": self.action_remove_song,
            "btn-pick": self.action_cherry_pick,
            "btn-export": self.action_export_playlist,
        }
        handler = mapping.get(event.button.id or "")
        if handler:
            handler()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_load_playlist(self) -> None:
        def on_result(playlist_id: str | None) -> None:
            if not playlist_id or self._provider is None:
                return
            playlist_id = playlist_id.strip()
            # Accept full URLs: https://open.spotify.com/playlist/<id>
            if "/" in playlist_id:
                playlist_id = playlist_id.rstrip("/").split("/")[-1].split("?")[0]
            try:
                playlist = self._provider.get_playlist(playlist_id)
                from .snapshot_handler import save_playlist_state, save_snapshot
                save_snapshot(playlist.service, playlist.service_id, playlist.songs)
                save_playlist_state(playlist)
                self._refresh_playlist_tree()
                self._show_songs(playlist)
                self.notify(f'Loaded "{playlist.name}"')
            except Exception as e:
                self.notify(f"Error: {e}", severity="error")

        provider_label = "Deezer" if self._provider and self._provider.service_name == "deezer" else "Spotify"
        self.push_screen(
            InputModal("Load playlist", f"{provider_label} playlist URL or ID"), on_result
        )

    def action_clone_playlist(self) -> None:
        if self._selected is None:
            self.notify("Select a playlist first.", severity="warning")
            return

        def on_result(name: str | None) -> None:
            if not name or self._provider is None or self._selected is None:
                return
            user_id = resolve_clone_user_id(self._provider)
            if user_id is None:
                self.notify("SPOTIFY_USER_ID not set in .env", severity="error")
                return
            try:
                new_playlist = clone(
                    self._provider,
                    user_id,
                    self._selected.service_id,
                    name,
                    description=f"Clone of {self._selected.name} — managed by SyncZik",
                )
                self._refresh_playlist_tree()
                self._show_songs(new_playlist)
                self.notify(f'Cloned to "{name}"')
            except Exception as e:
                self.notify(f"Error: {e}", severity="error")

        self.push_screen(
            InputModal("Clone playlist", f'Name for the clone of "{self._selected.name}"'),
            on_result,
        )

    def action_sync_playlist(self) -> None:
        if self._selected is None:
            self.notify("Select a playlist first.", severity="warning")
            return
        if self._provider is None:
            return

        try:
            result = sync(self._provider, self._selected)
        except Exception as e:
            self.notify(f"Sync error: {e}", severity="error")
            return

        if result.is_clean():
            self.notify("Already up to date.")
            self._show_songs(self._selected)
            return

        def on_result(songs_to_remove: list[Song]) -> None:
            if self._selected is None:
                return
            if songs_to_remove and self._provider:
                apply_remote_removal(self._provider, self._selected, songs_to_remove)
            self._refresh_playlist_tree()
            self._show_songs(self._selected)

        self.push_screen(SyncResultModal(result), on_result)

    def action_add_song(self) -> None:
        if self._selected is None:
            self.notify("Select a playlist first.", severity="warning")
            return
        if self._provider is None:
            return

        def on_result(song: Song | None) -> None:
            if song is None or self._selected is None:
                return
            added = add_song(self._selected, song)
            if added:
                self._show_songs(self._selected)
                self.notify(f'Added "{song.name}" (staged — Sync to push)')
            else:
                self.notify("Song already in playlist.", severity="warning")

        self.push_screen(SearchModal(self._provider), on_result)

    def action_remove_song(self) -> None:
        if self._selected is None:
            self.notify("Select a playlist first.", severity="warning")
            return
        table = self.query_one("#song-table", DataTable)
        row_key = table.cursor_row
        if row_key is None or row_key >= len(self._selected.songs):
            self.notify("Select a song to remove.", severity="warning")
            return
        song = self._selected.songs[row_key]
        removed = remove_song(self._selected, song)
        if removed:
            self._show_songs(self._selected)
            self.notify(f'Removed "{song.name}" (staged — Sync to push)')

    def action_cherry_pick(self) -> None:
        if self._selected is None:
            self.notify("Select a target playlist first.", severity="warning")
            return
        if self._provider is None:
            return

        def on_result(picked: list[Song]) -> None:
            if not picked or self._selected is None:
                return
            added = cherry_pick(self._selected, picked)
            if added:
                self._show_songs(self._selected)
                self.notify(f"Cherry-picked {len(added)} song(s) (staged — Sync to push)")
            else:
                self.notify("All selected songs already in playlist.", severity="warning")

        self.push_screen(CherryPickModal(self._provider, self._selected), on_result)

    def action_export_playlist(self) -> None:
        """Export the current playlist to another platform, resolving conflicts via GUI."""
        if self._selected is None:
            self.notify("Select a playlist first.", severity="warning")
            return
        if self._provider is None:
            return
        selected_name = self._selected.name

        def on_platform(platform: ServiceName | None) -> None:
            if platform is None:
                return

            try:
                target_provider = build_provider(platform)
            except RuntimeError as e:
                self.notify(str(e), severity="error")
                return
            user_id = resolve_clone_user_id(target_provider)
            if user_id is None:
                self.notify("SPOTIFY_USER_ID not set in .env", severity="error")
                return

            def on_name(export_name: str | None) -> None:
                if not export_name or self._selected is None:
                    return
                selected_name = self._selected.name
                try:
                    export_plan = plan_export(self._selected.songs, target_provider)
                except Exception as e:
                    self.notify(f"Export planning error: {e}", severity="error")
                    return

                if export_plan.is_clean():
                    # No conflicts — execute immediately
                    songs = [t for _, t in export_plan.auto_resolved]
                    execute_export(
                        target_provider, user_id, export_name, songs,
                        description=f"Exported from {selected_name} — managed by SyncZik",
                    )
                    self.notify(f'Exported "{export_name}" ({len(songs)} songs, no conflicts)')
                    return

                def on_resolved(resolved_songs: list[Song]) -> None:
                    try:
                        execute_export(
                            target_provider, user_id, export_name, resolved_songs,
                            description=f"Exported from {selected_name} — managed by SyncZik",
                        )
                        skipped = export_plan.total() - len(resolved_songs)
                        self.notify(
                            f'Exported "{export_name}" ({len(resolved_songs)} songs'
                            + (f", {skipped} skipped)" if skipped else ")")
                        )
                    except Exception as e:
                        self.notify(f"Export error: {e}", severity="error")

                self.push_screen(ExportConflictScreen(export_plan, target_provider), on_resolved)

            self.push_screen(
                InputModal("Export playlist", f'Name for the export of "{selected_name}"'),
                on_name,
            )

        self.push_screen(ProviderPickerModal(), on_platform)


def run() -> None:
    SyncZikApp().run()


if __name__ == "__main__":
    run()
