"""Review screen for entity merge candidates."""

from __future__ import annotations

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Static

from kg_world_anvil.tui.services import PendingReview


class ReviewScreen(Screen):
    BINDINGS = [
        ("escape", "app.switch_screen('ingest')", "Home"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._decisions: dict[tuple[str, str], str] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Review Entity Merges", classes="screen-title")
        yield DataTable(id="review-table")
        yield Horizontal(
            Button("Merge Selected", variant="primary", id="merge-btn"),
            Button("Create New", id="new-btn"),
            Button("Skip", id="skip-btn"),
            Button("Commit All", variant="success", id="commit-all-btn"),
        )
        yield Static("", id="review-status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#review-table", DataTable)
        table.add_columns("Extracted", "Type", "Best Match", "Score", "Decision")
        self.refresh_table()

    def refresh_table(self) -> None:
        table = self.query_one("#review-table", DataTable)
        table.clear()
        services = self.app.services  # type: ignore[attr-defined]
        for idx, item in enumerate(services.pending_reviews):
            best = item.candidates[0] if item.candidates else None
            key = (item.extracted_name.lower(), item.extracted_type.lower())
            decision = self._decisions.get(key, "pending")
            table.add_row(
                item.extracted_name,
                item.extracted_type,
                best.existing_name if best else "-",
                f"{best.score:.2f}" if best else "-",
                decision,
                key=str(idx),
            )

    @on(DataTable.RowSelected)
    def on_row_selected(self, event: DataTable.RowSelected) -> None:
        self._selected_row = event.row_key

    @on(Button.Pressed, "#merge-btn")
    def on_merge(self) -> None:
        self._set_decision("merge")

    @on(Button.Pressed, "#new-btn")
    def on_new(self) -> None:
        self._set_decision("create_new")

    @on(Button.Pressed, "#skip-btn")
    def on_skip(self) -> None:
        self._set_decision("skip")

    def _set_decision(self, decision: str) -> None:
        table = self.query_one("#review-table", DataTable)
        row_idx = table.cursor_row
        if row_idx is None:
            return
        services = self.app.services  # type: ignore[attr-defined]
        if row_idx >= len(services.pending_reviews):
            return
        item = services.pending_reviews[row_idx]
        key = (item.extracted_name.lower(), item.extracted_type.lower())
        self._decisions[key] = decision
        self.refresh_table()
        self.query_one("#review-status", Static).update(f"Set {item.extracted_name} -> {decision}")

    @on(Button.Pressed, "#commit-all-btn")
    def on_commit_all(self) -> None:
        self.commit_all()

    @work(exclusive=True)
    async def commit_all(self) -> None:
        status = self.query_one("#review-status", Static)
        services = self.app.services  # type: ignore[attr-defined]
        decisions = dict(self._decisions)
        for item in services.pending_reviews:
            key = (item.extracted_name.lower(), item.extracted_type.lower())
            decisions.setdefault(key, "create_new")
        status.update("[yellow]Committing...[/yellow]")
        try:
            entities, rels = await services.commit_extraction(decisions)
            status.update(f"[green]Committed {entities} entities and {rels} relationships.[/green]")
            self._decisions.clear()
            self.refresh_table()
        except Exception as exc:
            status.update(f"[red]Commit failed: {exc}[/red]")
