"""Inconsistencies screen."""

from __future__ import annotations

from textual import on, work
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Static


class InconsistenciesScreen(Screen):
    BINDINGS = [
        ("escape", "app.switch_screen('ingest')", "Home"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Consistency Checks", classes="screen-title")
        yield Button("Run Checks", variant="primary", id="run-checks-btn")
        yield DataTable(id="issues-table")
        yield Static("", id="issues-status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#issues-table", DataTable)
        table.add_columns("Severity", "Rule", "Message")

    @on(Button.Pressed, "#run-checks-btn")
    def on_run_checks(self) -> None:
        self.run_checks()

    @work(exclusive=True)
    async def run_checks(self) -> None:
        status = self.query_one("#issues-status", Static)
        table = self.query_one("#issues-table", DataTable)
        table.clear()
        status.update("[yellow]Running consistency checks...[/yellow]")
        try:
            services = self.app.services  # type: ignore[attr-defined]
            issues = await services.consistency.run_all()
            for issue in issues:
                table.add_row(issue.severity, issue.rule_name, issue.message)
            if issues:
                status.update(f"[yellow]Found {len(issues)} issue(s).[/yellow]")
            else:
                status.update("[green]No inconsistencies found.[/green]")
        except Exception as exc:
            status.update(f"[red]Checks failed: {exc}[/red]")
