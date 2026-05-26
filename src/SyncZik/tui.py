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

from .auth import get_spotify_client
from .config import SPOTIFY_USER_ID
from .providers.spotify import SpotifyProvider
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


class SearchModal(ModalScreen[Song | None]):
    """Search for a track and let the user pick one."""

    def __init__(self, provider: SpotifyProvider) -> None:
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
    ]

    def __init__(self) -> None:
        super().__init__()
        self._provider: SpotifyProvider | None = None
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
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#song-table", DataTable)
        table.add_columns("Title", "Artist", "Status")

        tree = self.query_one("#playlist-tree", Tree)
        tree.root.expand()

        self._provider = SpotifyProvider(get_spotify_client())
        self._refresh_playlist_tree()

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
            parent_node = roots.get(p.parent_id)
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

        self.push_screen(InputModal("Load playlist", "Spotify playlist URL or ID"), on_result)

    def action_clone_playlist(self) -> None:
        if self._selected is None:
            self.notify("Select a playlist first.", severity="warning")
            return

        def on_result(name: str | None) -> None:
            if not name or self._provider is None:
                return
            user_id = SPOTIFY_USER_ID
            if not user_id:
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
            if songs_to_remove and self._selected and self._provider:
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


def run() -> None:
    SyncZikApp().run()


if __name__ == "__main__":
    run()
