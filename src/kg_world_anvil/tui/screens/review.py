"""Review screen for staging entity merge and survivor-type decisions."""

from __future__ import annotations

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Static

from kg_world_anvil.tui.screens.ingest import IngestScreen


class ReviewScreen(Screen):
    BINDINGS = [
        ("escape", "app.switch_screen('ingest')", "Home"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._decisions: dict[str, str] = {}
        self._survivor_types: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Review Staging vs Production", classes="screen-title")
        yield DataTable(id="review-table")
        yield Horizontal(
            Button("Merge to Prod", variant="primary", id="merge-btn"),
            Button("Create New", id="new-btn"),
            Button("Skip", id="skip-btn"),
            Button("Cycle Survivor Type", id="type-btn"),
            Button("Promote All", variant="success", id="commit-all-btn"),
            Button("Discard Draft", variant="error", id="discard-btn"),
        )
        yield Static("", id="review-status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#review-table", DataTable)
        table.add_columns(
            "Name",
            "Staging Types",
            "Prod Match",
            "Survivor Type",
            "Decision",
        )
        self.refresh_table()

    def refresh_table(self) -> None:
        table = self.query_one("#review-table", DataTable)
        table.clear()
        services = self.app.services  # type: ignore[attr-defined]
        if services is None:
            return
        for idx, item in enumerate(services.pending_reviews):
            best = item.prod_candidates[0] if item.prod_candidates else None
            decision = self._decisions.get(item.canonical_key, "pending")
            survivor = self._survivor_types.get(
                item.canonical_key,
                item.staging_types[0] if item.staging_types else "-",
            )
            table.add_row(
                item.display_name,
                ", ".join(item.staging_types),
                best.existing_name if best else "-",
                survivor,
                decision,
                key=str(idx),
            )

    @on(Button.Pressed, "#merge-btn")
    def on_merge(self) -> None:
        self._set_decision("merge")

    @on(Button.Pressed, "#new-btn")
    def on_new(self) -> None:
        self._set_decision("create_new")

    @on(Button.Pressed, "#skip-btn")
    def on_skip(self) -> None:
        self._set_decision("skip")

    @on(Button.Pressed, "#type-btn")
    def on_cycle_type(self) -> None:
        table = self.query_one("#review-table", DataTable)
        row_idx = table.cursor_row
        if row_idx is None:
            return
        services = self.app.services  # type: ignore[attr-defined]
        if row_idx >= len(services.pending_reviews):
            return
        item = services.pending_reviews[row_idx]
        if len(item.staging_types) <= 1:
            self.query_one("#review-status", Static).update(
                "Only one staging type; survivor type unchanged."
            )
            return
        current = self._survivor_types.get(
            item.canonical_key, item.staging_types[0]
        )
        try:
            idx = item.staging_types.index(current)
        except ValueError:
            idx = -1
        next_type = item.staging_types[(idx + 1) % len(item.staging_types)]
        self._survivor_types[item.canonical_key] = next_type
        self.refresh_table()
        self.query_one("#review-status", Static).update(
            f"Survivor type for {item.display_name} -> {next_type}"
        )

    def _set_decision(self, decision: str) -> None:
        table = self.query_one("#review-table", DataTable)
        row_idx = table.cursor_row
        if row_idx is None:
            return
        services = self.app.services  # type: ignore[attr-defined]
        if row_idx >= len(services.pending_reviews):
            return
        item = services.pending_reviews[row_idx]
        self._decisions[item.canonical_key] = decision
        if decision == "merge" and item.prod_candidates:
            self._survivor_types[item.canonical_key] = item.prod_candidates[0].existing_type
        self.refresh_table()
        self.query_one("#review-status", Static).update(
            f"Set {item.display_name} -> {decision}"
        )

    @on(Button.Pressed, "#commit-all-btn")
    def on_commit_all(self) -> None:
        self.promote_all()

    @on(Button.Pressed, "#discard-btn")
    def on_discard(self) -> None:
        self.discard_draft()

    @work(exclusive=True)
    async def promote_all(self) -> None:
        status = self.query_one("#review-status", Static)
        services = self.app.services  # type: ignore[attr-defined]
        decisions = dict(self._decisions)
        for item in services.pending_reviews:
            decisions.setdefault(item.canonical_key, "create_new")
        status.update("[yellow]Promoting staging batch...[/yellow]")
        try:
            result = await services.promote_draft_batch(
                merge_decisions=decisions,
                survivor_types=dict(self._survivor_types),
            )
            msg = (
                f"[green]Promoted: {result.entities_created} created, "
                f"{result.entities_updated} updated, "
                f"{result.edges_created} edges, "
                f"{result.edges_skipped} edges skipped "
                f"({result.staging_groups_collapsed} groups collapsed).[/green]"
            )
            status.update(msg)
            IngestScreen.clear_input_on_app(self.app)
            self._decisions.clear()
            self._survivor_types.clear()
            self.refresh_table()
        except Exception as exc:
            status.update(f"[red]Promote failed: {exc}[/red]")

    @work(exclusive=True)
    async def discard_draft(self) -> None:
        status = self.query_one("#review-status", Static)
        services = self.app.services  # type: ignore[attr-defined]
        status.update("[yellow]Discarding draft...[/yellow]")
        try:
            await services.discard_draft_batch()
            status.update("[green]Draft discarded.[/green]")
            self._decisions.clear()
            self._survivor_types.clear()
            self.refresh_table()
        except Exception as exc:
            status.update(f"[red]Discard failed: {exc}[/red]")
