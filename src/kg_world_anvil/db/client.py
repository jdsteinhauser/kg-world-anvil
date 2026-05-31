"""SurrealDB connection and schema bootstrap."""

from __future__ import annotations

from pathlib import Path

from surrealdb import AsyncSurreal

from kg_world_anvil.config import Settings, get_settings


class DatabaseClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._db: AsyncSurreal | None = None

    @property
    def db(self) -> AsyncSurreal:
        if self._db is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._db

    async def connect(self) -> AsyncSurreal:
        if self._db is not None:
            return self._db

        self._db = AsyncSurreal(self.settings.surreal_url)
        await self._db.connect()
        await self._db.signin(
            {"username": self.settings.surreal_user, "password": self.settings.surreal_pass}
        )
        await self._db.use(self.settings.surreal_ns, self.settings.surreal_db)
        await self._bootstrap_schema()
        return self._db

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def _bootstrap_schema(self) -> None:
        schema_path = self.settings.schema_path
        if not schema_path.exists():
            return
        schema_sql = schema_path.read_text(encoding="utf-8")
        statements = [s.strip() for s in schema_sql.split(";") if s.strip()]
        for statement in statements:
            try:
                await self._db.query(statement)
            except Exception:
                # Schema statements may already exist on subsequent runs.
                pass

    async def query(self, sql: str, vars: dict | None = None) -> list:
        result = await self.db.query(sql, vars or {})
        if isinstance(result, list):
            return result
        return [result]

    async def __aenter__(self) -> AsyncSurreal:
        return await self.connect()

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()


def load_schema_text(path: Path | None = None) -> str:
    settings = get_settings()
    schema_path = path or settings.schema_path
    return schema_path.read_text(encoding="utf-8")
