"""Main Textual application."""

from __future__ import annotations

from textual.app import App
from textual.binding import Binding

from kg_world_anvil.tui.screens.graph import GraphScreen
from kg_world_anvil.tui.screens.inconsistencies import InconsistenciesScreen
from kg_world_anvil.tui.screens.ingest import IngestScreen
from kg_world_anvil.tui.screens.query import QueryScreen
from kg_world_anvil.tui.screens.review import ReviewScreen
from kg_world_anvil.tui.services import AppServices


class KgApp(App):
    TITLE = "kg-world-anvil"
    CSS = """
    Screen {
        layout: vertical;
    }
    .screen-title {
        padding: 1 2;
        text-style: bold;
    }
    .section-title {
        padding: 0 2;
        color: $accent;
    }
    #ingest-text {
        height: 1fr;
        margin: 0 2;
    }
    #ingest-actions {
        height: auto;
        padding: 1 2;
    }
    #ingest-status, #review-status, #graph-status, #query-status, #issues-status {
        padding: 0 2 1 2;
    }
    #entity-table, #edge-table, #review-table, #query-results, #issues-table {
        height: 1fr;
        margin: 0 2;
    }
    #raw-sql, #generated-sql {
        height: 8;
        margin: 0 2;
    }
    #nl-question, #saved-param-1, #saved-param-2 {
        margin: 0 2;
    }
    """

    BINDINGS = [
        Binding("i", "show_screen('ingest')", "Ingest"),
        Binding("r", "show_screen('review')", "Review"),
        Binding("g", "show_screen('graph')", "Graph"),
        Binding("/", "show_screen('query')", "Query"),
        Binding("c", "show_screen('inconsistencies')", "Checks"),
        Binding("ctrl+q", "quit", "Quit"),
    ]

    SCREENS = {
        "ingest": IngestScreen,
        "review": ReviewScreen,
        "graph": GraphScreen,
        "query": QueryScreen,
        "inconsistencies": InconsistenciesScreen,
    }

    def __init__(self) -> None:
        super().__init__()
        self.services: AppServices | None = None

    async def on_mount(self) -> None:
        self.push_screen("ingest")

        try:
            self.services = await AppServices.create()
        except Exception as exc:
            self.notify(f"Failed to connect to SurrealDB: {exc}", severity="error")

    async def on_unmount(self) -> None:
        if self.services:
            await self.services.close()

    def action_show_screen(self, screen_name: str) -> None:
        self.switch_screen(screen_name)


def run_app() -> None:
    app = KgApp()
    app.run()
