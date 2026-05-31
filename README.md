# kg-world-anvil

Turn unstructured text (HTML, Markdown, BBCode, or plain text) into a normalized knowledge graph stored in SurrealDB, with a Textual TUI for ingestion, review, querying, and consistency checks.

## Prerequisites

- Python 3.11+
- [SurrealDB](https://surrealdb.com/docs/surrealdb/installation) installed locally
- OpenAI API key

## Setup

```bash
# Create virtual environment
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # Linux/macOS

# Install package
pip install -e .

# Configure environment
copy .env.example .env
# Edit .env with your OPENAI_API_KEY
```

## Start SurrealDB

```bash
mkdir -p data
surreal start --user root --pass root rocksdb:./data/kg.db
```

Leave this running in a separate terminal.

## Run the TUI

```bash
kg
```

## Features

- **Ingest** — Load or paste text; extract entities and relationships via OpenAI structured outputs
- **Review** — Resolve ambiguous entity merges before committing to the graph
- **Graph browser** — Search entities and explore neighbors
- **Query** — Natural language, saved queries, or raw SurrealQL
- **Inconsistencies** — Detect type conflicts, contradictory edges, and more

## Development

```bash
pip install -e ".[dev]"
pytest
```
