"""Ingest screen."""

from __future__ import annotations

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Select, Static, TextArea

from kg_world_anvil.models import TextFormat


class IngestScreen(Screen):
    BINDINGS = [
        ("escape", "app.switch_screen('ingest')", "Home"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Ingest Text", classes="screen-title")
        yield Select(
            [
                ("Plain text", "plain"),
                ("HTML", "html"),
                ("Markdown", "markdown"),
                ("BBCode", "bbcode"),
                ("Auto-detect", "auto"),
            ],
            prompt="Format",
            id="format-select",
        )
        yield TextArea(id="ingest-text", language="markdown")
        yield Horizontal(
            Button("Extract", variant="primary", id="extract-btn"),
            Button("Commit to Graph", id="commit-btn"),
            Button("Review Queue", id="review-btn"),
            id="ingest-actions",
        )
        yield Static("Paste or load text, then extract entities and relationships.", id="ingest-status")
        yield Footer()

    @on(Button.Pressed, "#extract-btn")
    def on_extract(self) -> None:
        self.extract_knowledge()

    @on(Button.Pressed, "#commit-btn")
    def on_commit(self) -> None:
        self.commit_to_graph()

    @on(Button.Pressed, "#review-btn")
    def on_review(self) -> None:
        self.app.switch_screen("review")

    @work(exclusive=True)
    async def extract_knowledge(self) -> None:
        status = self.query_one("#ingest-status", Static)
        text_area = self.query_one("#ingest-text", TextArea)
        fmt_select = self.query_one("#format-select", Select)
        raw = text_area.text.strip()
        if not raw:
            status.update("[red]No text to extract.[/red]")
            return
        fmt_value = str(fmt_select.value)
        fmt = None if fmt_value == "auto" else TextFormat(fmt_value)
        status.update("[yellow]Extracting...[/yellow]")
        try:
            services = self.app.services  # type: ignore[attr-defined]
            result, doc_id = await services.ingest_and_extract(raw, fmt)
            status.update(
                f"[green]Extracted {len(result.entities)} entities and "
                f"{len(result.relationships)} relationships (doc: {doc_id}). "
                f"{len(services.pending_reviews)} items need review.[/green]"
            )
        except Exception as exc:
            status.update(f"[red]Extraction failed: {exc}[/red]")

    @work(exclusive=True)
    async def commit_to_graph(self) -> None:
        status = self.query_one("#ingest-status", Static)
        services = self.app.services  # type: ignore[attr-defined]
        if not services.last_extraction:
            status.update("[red]Run extraction first.[/red]")
            return
        if services.pending_reviews:
            status.update("[yellow]Pending reviews exist. Resolve them or commit with defaults.[/yellow]")
            self.app.switch_screen("review")
            return
        status.update("[yellow]Committing...[/yellow]")
        try:
            entities, rels = await services.commit_extraction({})
            status.update(f"[green]Committed {entities} new entities and {rels} relationships.[/green]")
        except Exception as exc:
            status.update(f"[red]Commit failed: {exc}[/red]")
