"""Application configuration."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-2024-08-06"
    openai_embedding_model: str = "text-embedding-3-small"

    surreal_url: str = "ws://localhost:8000/rpc"
    surreal_user: str = "root"
    surreal_pass: str = "root"
    surreal_ns: str = "kg"
    surreal_db: str = "world_anvil"

    use_embeddings: bool = False
    embedding_dim: int = 1536
    fuzzy_match_threshold: int = 85

    chunk_size: int = 4000
    chunk_overlap: int = 400

    rag_chunk_size: int = 800
    rag_chunk_overlap: int = 150
    rag_top_k: int = 6

    auto_dedup: bool = True
    dedup_policy: str = "type-rank"
    dedup_type_rank: str = (
        "city,town,village,settlement,region,location,building,geographical feature,country"
    )

    use_staging: bool = True

    @property
    def schema_path(self) -> Path:
        return Path(__file__).resolve().parent.parent.parent / "schema.surql"


def get_settings() -> Settings:
    return Settings()
