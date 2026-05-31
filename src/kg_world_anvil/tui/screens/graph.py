"""Graph browser screen."""

from __future__ import annotations

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, Static


class GraphScreen(Screen):
    BINDINGS = [
        ("escape", "app.switch_screen('ingest')", "Home"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Graph Browser", classes="screen-title")
        yield Horizontal(
            Input(placeholder="Search entities...", id="graph-search"),
            Button("Search", variant="primary", id="graph-search-btn"),
        )
        yield Static("Entities", classes="section-title")
        yield DataTable(id="entity-table")
        yield Static("Relationships", classes="section-title")
        yield DataTable(id="edge-table")
        yield Static("", id="graph-status")
        yield Footer()

    def on_mount(self) -> None:
        entity_table = self.query_one("#entity-table", DataTable)
        entity_table.add_columns("Name", "Type", "Aliases", "ID")
        edge_table = self.query_one("#edge-table", DataTable)
        edge_table.add_columns("From", "Predicate", "To", "Confidence")
        self.search_entities()

    @on(Button.Pressed, "#graph-search-btn")
    def on_search(self) -> None:
        self.search_entities()

    @on(Input.Submitted, "#graph-search")
    def on_search_submit(self) -> None:
        self.search_entities()

    @work(exclusive=True)
    async def search_entities(self) -> None:
        status = self.query_one("#graph-status", Static)
        search = self.query_one("#graph-search", Input).value.strip()
        entity_table = self.query_one("#entity-table", DataTable)
        entity_table.clear()
        try:
            services = self.app.services  # type: ignore[attr-defined]
            entities = await services.repo.list_entities(search=search)
            for entity in entities:
                entity_table.add_row(
                    entity.name,
                    entity.type,
                    ", ".join(entity.aliases[:3]),
                    entity.id or "",
                    key=entity.id or entity.name,
                )
            status.update(f"[green]Found {len(entities)} entities.[/green]")
        except Exception as exc:
            status.update(f"[red]Search failed: {exc}[/red]")

    @on(DataTable.RowSelected, "#entity-table")
    def on_entity_selected(self, event: DataTable.RowSelected) -> None:
        self.load_neighbors(event.row_key.value if event.row_key else "")

    @work(exclusive=True)
    async def load_neighbors(self, entity_id: str) -> None:
        if not entity_id:
            return
        edge_table = self.query_one("#edge-table", DataTable)
        edge_table.clear()
        status = self.query_one("#graph-status", Static)
        try:
            services = self.app.services  # type: ignore[attr-defined]
            edges = await services.repo.get_entity_neighbors(entity_id)
            for edge in edges:
                edge_table.add_row(
                    edge.from_entity_name or edge.from_entity_id,
                    edge.predicate,
                    edge.to_entity_name or edge.to_entity_id,
                    f"{edge.confidence:.2f}",
                )
            status.update(f"[green]Loaded {len(edges)} relationships.[/green]")
        except Exception as exc:
            status.update(f"[red]Failed to load relationships: {exc}[/red]")
