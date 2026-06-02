"""Query screen with NL, Ask (RAG), saved, and raw SurrealQL modes."""

from __future__ import annotations

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, Select, Static, TextArea

from kg_world_anvil.query.queries import SAVED_QUERIES


class QueryScreen(Screen):
    BINDINGS = [
        ("escape", "app.switch_screen('ingest')", "Home"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Query Knowledge Graph", classes="screen-title")
        yield Select(
            [
                ("Natural Language", "nl"),
                ("Ask (RAG)", "ask"),
                ("Saved Query", "saved"),
                ("Raw SurrealQL", "raw"),
            ],
            value="nl",
            id="query-mode",
        )
        yield Input(placeholder="Ask a question in natural language...", id="nl-question")
        yield Select(
            [(meta["label"], qid) for qid, meta in SAVED_QUERIES.items()],
            prompt="Saved query",
            id="saved-query-select",
        )
        yield Input(placeholder="Parameter value", id="saved-param-1")
        yield Input(placeholder="Second parameter (if needed)", id="saved-param-2")
        yield TextArea("", id="raw-sql", language="sql")
        yield TextArea("", id="generated-sql", language="sql", read_only=True)
        yield TextArea("", id="rag-answer", read_only=True)
        yield Horizontal(
            Button("Generate SQL", variant="primary", id="generate-btn"),
            Button("Run Query", variant="success", id="run-btn"),
            Button("Edit Generated SQL", id="edit-btn"),
        )
        yield DataTable(id="query-results")
        yield Static("", id="query-status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#query-results", DataTable)
        self._result_table = table
        self.query_one("#raw-sql", TextArea).text = "SELECT * FROM entity LIMIT 20;"
        self._update_mode_visibility("nl")

    @on(Button.Pressed, "#generate-btn")
    def on_generate(self) -> None:
        self.generate_sql()

    @on(Button.Pressed, "#run-btn")
    def on_run(self) -> None:
        self.run_query()

    @on(Button.Pressed, "#edit-btn")
    def on_edit(self) -> None:
        generated = self.query_one("#generated-sql", TextArea)
        raw = self.query_one("#raw-sql", TextArea)
        raw.text = generated.text
        self.query_one("#query-mode", Select).value = "raw"
        self._update_mode_visibility("raw")

    def _update_mode_visibility(self, mode: str) -> None:
        self.query_one("#nl-question").display = mode in {"nl", "ask"}
        self.query_one("#saved-query-select").display = mode == "saved"
        self.query_one("#saved-param-1").display = mode == "saved"
        self.query_one("#saved-param-2").display = mode == "saved"
        self.query_one("#generate-btn").display = mode == "nl"
        self.query_one("#generated-sql").display = mode == "nl"
        self.query_one("#edit-btn").display = mode == "nl"
        self.query_one("#raw-sql").display = mode == "raw"
        self.query_one("#rag-answer").display = mode == "ask"
        self.query_one("#query-results").display = mode != "ask"

    @on(Select.Changed, "#query-mode")
    def on_mode_changed(self, event: Select.Changed) -> None:
        self._update_mode_visibility(str(event.value))

    @work(exclusive=True)
    async def generate_sql(self) -> None:
        status = self.query_one("#query-status", Static)
        question = self.query_one("#nl-question", Input).value.strip()
        if not question:
            status.update("[red]Enter a natural language question.[/red]")
            return
        status.update("[yellow]Generating SurrealQL...[/yellow]")
        try:
            services = self.app.services  # type: ignore[attr-defined]
            generated = services.nl_translator.translate(question)
            self.query_one("#generated-sql", TextArea).text = generated.surrealql
            status.update(f"[green]{generated.explanation or 'Query generated.'}[/green]")
        except Exception as exc:
            status.update(f"[red]Generation failed: {exc}[/red]")

    @work(exclusive=True)
    async def run_query(self) -> None:
        status = self.query_one("#query-status", Static)
        mode = str(self.query_one("#query-mode", Select).value)
        services = self.app.services  # type: ignore[attr-defined]
        status.update("[yellow]Running query...[/yellow]")
        try:
            if mode == "ask":
                question = self.query_one("#nl-question", Input).value.strip()
                if not question:
                    status.update("[red]Enter a question to ask.[/red]")
                    return
                answer = await services.rag_service.answer(question)
                self.query_one("#rag-answer", TextArea).text = answer.answer
                if answer.citations:
                    cites = "\n".join(
                        f"- {item.document_id} chunk {item.seq}: {item.snippet[:120]}..."
                        for item in answer.citations
                    )
                    status.update(f"[green]Answer generated with {len(answer.citations)} citation(s).[/green]\n{cites}")
                else:
                    status.update("[green]Answer generated.[/green]")
                return

            if mode == "nl":
                sql = self.query_one("#generated-sql", TextArea).text.strip()
                if not sql:
                    status.update("[red]Generate SQL first.[/red]")
                    return
                result = await services.query_service.run_raw(sql)
            elif mode == "saved":
                qid = str(self.query_one("#saved-query-select", Select).value)
                meta = SAVED_QUERIES[qid]
                params: dict[str, str] = {}
                param_values = [
                    self.query_one("#saved-param-1", Input).value.strip(),
                    self.query_one("#saved-param-2", Input).value.strip(),
                ]
                for idx, param_name in enumerate(meta["params"]):
                    if idx < len(param_values) and param_values[idx]:
                        params[param_name] = param_values[idx]
                if len(params) < len(meta["params"]):
                    status.update("[red]Fill in all query parameters.[/red]")
                    return
                result = await services.query_service.run_saved(qid, params)
            else:
                sql = self.query_one("#raw-sql", TextArea).text.strip()
                result = await services.query_service.run_raw(sql)

            table = self.query_one("#query-results", DataTable)
            table.clear(columns=True)
            if result.columns:
                table.add_columns(*result.columns)
            for row in result.rows:
                table.add_row(*[str(cell) for cell in row])
            status.update(f"[green]{len(result.rows)} row(s) returned.[/green]")
        except Exception as exc:
            status.update(f"[red]Query failed: {exc}[/red]")
