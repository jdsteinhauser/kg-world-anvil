"""Entity deduplication review screen."""

from __future__ import annotations

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Select, Static

from kg_world_anvil.models import DuplicateGroup, MergePlan


class DedupScreen(Screen):
    BINDINGS = [
        ("escape", "app.switch_screen('ingest')", "Home"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._groups: list[DuplicateGroup] = []
        self._selected_index: int | None = None
        self._current_plan: MergePlan | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Entity Deduplication", classes="screen-title")
        yield Horizontal(
            Button("Scan", variant="primary", id="scan-btn"),
            id="dedup-actions-top",
        )
        yield DataTable(id="dedup-table")
        yield Static("Select a group to choose survivor type.", id="dedup-detail")
        yield Select([], prompt="Survivor type", id="survivor-type-select")
        yield Horizontal(
            Button("Preview Plan", id="preview-btn"),
            Button("Apply Merge", variant="success", id="apply-btn"),
            id="dedup-actions",
        )
        yield Static("", id="dedup-status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#dedup-table", DataTable)
        table.add_columns("Key", "Name", "Types", "Count", "Suggested")

    @on(Button.Pressed, "#scan-btn")
    def on_scan(self) -> None:
        self.scan_duplicates()

    @on(DataTable.RowSelected)
    def on_row_selected(self, event: DataTable.RowSelected) -> None:
        table = self.query_one("#dedup-table", DataTable)
        row_idx = table.cursor_row
        if row_idx is None or row_idx >= len(self._groups):
            return
        self._selected_index = row_idx
        group = self._groups[row_idx]
        self._current_plan = None
        detail = self.query_one("#dedup-detail", Static)
        names = ", ".join(sorted({m.name for m in group.members}))
        detail.update(f"[bold]{group.canonical_key}[/bold] — {names}")
        type_select = self.query_one("#survivor-type-select", Select)
        options = [(m.type, m.type) for m in group.members]
        type_select.set_options(options)
        suggested = group.suggested_survivor_type
        if suggested:
            type_select.value = suggested

    @on(Button.Pressed, "#preview-btn")
    def on_preview(self) -> None:
        self.preview_plan()

    @on(Button.Pressed, "#apply-btn")
    def on_apply(self) -> None:
        self.apply_merge()

    @work(exclusive=True)
    async def scan_duplicates(self) -> None:
        status = self.query_one("#dedup-status", Static)
        table = self.query_one("#dedup-table", DataTable)
        table.clear()
        self._groups.clear()
        self._selected_index = None
        self._current_plan = None
        status.update("[yellow]Scanning for duplicate entities...[/yellow]")
        try:
            services = self.app.services  # type: ignore[attr-defined]
            if services is None:
                status.update("[red]Database not connected.[/red]")
                return
            self._groups = await services.scan_duplicates()
            for group in self._groups:
                types = ", ".join(sorted({m.type for m in group.members}))
                names = ", ".join(sorted({m.name for m in group.members})[:3])
                table.add_row(
                    group.canonical_key,
                    names,
                    types,
                    str(len(group.members)),
                    group.suggested_survivor_type,
                )
            if self._groups:
                status.update(f"[yellow]Found {len(self._groups)} duplicate group(s).[/yellow]")
            else:
                status.update("[green]No duplicate groups found.[/green]")
        except Exception as exc:
            status.update(f"[red]Scan failed: {exc}[/red]")

    @work(exclusive=True)
    async def preview_plan(self) -> None:
        status = self.query_one("#dedup-status", Static)
        if self._selected_index is None:
            status.update("[red]Select a group first.[/red]")
            return
        type_select = self.query_one("#survivor-type-select", Select)
        survivor_type = str(type_select.value) if type_select.value is not Select.NULL else ""
        if not survivor_type:
            status.update("[red]Choose a survivor type.[/red]")
            return
        try:
            services = self.app.services  # type: ignore[attr-defined]
            group = self._groups[self._selected_index]
            plan = await services.deduplicator.plan_merge(group, survivor_type)
            if plan is None:
                status.update("[red]Could not build merge plan for that type.[/red]")
                return
            self._current_plan = plan
            status.update(
                f"[green]Plan: keep {plan.survivor_name} ({plan.survivor_type}), "
                f"remove {len(plan.loser_ids)} entity/entities, "
                f"rewire ~{plan.edges_to_rewire} edge(s).[/green]"
            )
        except Exception as exc:
            status.update(f"[red]Preview failed: {exc}[/red]")

    @work(exclusive=True)
    async def apply_merge(self) -> None:
        status = self.query_one("#dedup-status", Static)
        if self._current_plan is None:
            status.update("[red]Preview a plan first.[/red]")
            return
        try:
            services = self.app.services  # type: ignore[attr-defined]
            rewired = await services.apply_dedup(self._current_plan)
            status.update(
                f"[green]Merged group '{self._current_plan.canonical_key}' — "
                f"rewired {rewired} edge(s).[/green]"
            )
            self._current_plan = None
            self.scan_duplicates()
        except Exception as exc:
            status.update(f"[red]Merge failed: {exc}[/red]")
