"""Ingest screen."""

from __future__ import annotations

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Select, Static, TextArea

from kg_world_anvil.models import TextFormat, parse_text_format


def resolve_text_format(fmt_select: Select) -> TextFormat | None:
    """Map Select value to TextFormat, treating unset/auto as auto-detect."""
    value = fmt_select.value
    if value is Select.NULL or value == Select.NULL:
        return None
    return parse_text_format(value)


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
            value="auto",
            id="format-select",
        )
        yield TextArea(id="ingest-text", language="markdown")
        yield Horizontal(
            Button("Extract", variant="primary", id="extract-btn"),
            Button("Promote to Graph", id="commit-btn"),
            Button("Review Queue", id="review-btn"),
            Button("Discard Draft", id="discard-btn"),
            id="ingest-actions",
        )
        yield Static("Paste or load text, then extract entities and relationships.", id="ingest-status")
        yield Footer()

    def clear_input(self) -> None:
        """Clear the ingest text area (e.g. after a successful promote)."""
        self.query_one("#ingest-text", TextArea).clear()

    @staticmethod
    def clear_input_on_app(app) -> None:
        """Clear ingest text from another screen when ingest may not be active."""
        try:
            ingest = app.get_screen("ingest")
        except Exception:
            return
        if isinstance(ingest, IngestScreen):
            ingest.clear_input()

    @on(Button.Pressed, "#extract-btn")
    def on_extract(self) -> None:
        self.extract_knowledge()

    @on(Button.Pressed, "#commit-btn")
    def on_commit(self) -> None:
        self.promote_to_graph()

    @on(Button.Pressed, "#review-btn")
    def on_review(self) -> None:
        self.app.switch_screen("review")

    @on(Button.Pressed, "#discard-btn")
    def on_discard(self) -> None:
        self.discard_draft()

    @work(exclusive=True)
    async def extract_knowledge(self) -> None:
        status = self.query_one("#ingest-status", Static)
        text_area = self.query_one("#ingest-text", TextArea)
        fmt_select = self.query_one("#format-select", Select)
        raw = text_area.text.strip()
        if not raw:
            status.update("[red]No text to extract.[/red]")
            return
        try:
            fmt = resolve_text_format(fmt_select)
        except ValueError as exc:
            status.update(f"[red]Invalid format selection: {exc}[/red]")
            return
        status.update("[yellow]Extracting...[/yellow]")
        text_area.loading = True
        try:
            services = self.app.services  # type: ignore[attr-defined]
            if services is None:
                status.update(
                    "[red]Database not connected. Start SurrealDB and restart the app.[/red]"
                )
                return
            result, doc_id = await services.ingest_and_extract(raw, fmt)
            draft_note = ""
            if services.draft_batch and services.draft_batch.id:
                draft_note = f" Staging batch: {services.draft_batch.id}."
            status.update(
                f"[green]Extracted {len(result.entities)} entities and "
                f"{len(result.relationships)} relationships (doc: {doc_id})."
                f"{draft_note} "
                f"{len(services.pending_reviews)} items need review.[/green]"
            )
        except RuntimeError as exc:
            status.update(f"[red]{exc}[/red]")
        except Exception as exc:
            status.update(f"[red]Extraction failed: {exc}[/red]")
        finally:
            text_area.loading = False

    @work(exclusive=True)
    async def promote_to_graph(self) -> None:
        status = self.query_one("#ingest-status", Static)
        services = self.app.services  # type: ignore[attr-defined]
        if services is None:
            status.update(
                "[red]Database not connected. Start SurrealDB and restart the app.[/red]"
            )
            return
        if not services.draft_batch:
            status.update("[red]Run extraction first (no staging draft).[/red]")
            return
        if services.pending_reviews:
            status.update(
                "[yellow]Pending reviews exist. Resolve them or promote with defaults.[/yellow]"
            )
            self.app.switch_screen("review")
            return
        status.update("[yellow]Promoting staging batch...[/yellow]")
        try:
            result = await services.promote_draft_batch({})
            self.clear_input()
            status.update(
                f"[green]Promoted {result.entities_created} new entities, "
                f"updated {result.entities_updated}, "
                f"created {result.edges_created} relationships "
                f"({result.edges_skipped} skipped).[/green]"
            )
        except Exception as exc:
            status.update(f"[red]Promote failed: {exc}[/red]")

    @work(exclusive=True)
    async def discard_draft(self) -> None:
        status = self.query_one("#ingest-status", Static)
        services = self.app.services  # type: ignore[attr-defined]
        if services is None:
            status.update(
                "[red]Database not connected. Start SurrealDB and restart the app.[/red]"
            )
            return
        if not services.draft_batch:
            status.update("[yellow]No draft staging batch to discard.[/yellow]")
            return
        try:
            await services.discard_draft_batch()
            status.update("[green]Draft discarded.[/green]")
        except Exception as exc:
            status.update(f"[red]Discard failed: {exc}[/red]")
