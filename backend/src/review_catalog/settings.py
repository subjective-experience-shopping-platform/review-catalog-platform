from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="REVIEW_CATALOG_",
        env_file=".env",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://catalog:catalog@localhost:5433/review_catalog"
    airflow_base_url: str = "http://localhost:8080"
    airflow_username: str = "airflow"
    airflow_password: str = "airflow"
    airflow_dag_id: str = "Catalog_ingestion"
    airflow_request_timeout_seconds: float = 10.0

    catalog_data_root: Path = PROJECT_ROOT / "data/runtime"
    experiment_markdown_path: Path = PACKAGE_ROOT / "content/experiment.md"
    readme_request_timeout_seconds: float = 10.0
    taxonomy_manifest_path: Path = PROJECT_ROOT / "config/taxonomy/2026-10-05_142933.json"
    normalization_config_path: Path = PROJECT_ROOT / "config/normalization/2026-10-05_142933.yaml"
    bootstrap_source_root: Path = PROJECT_ROOT / "data/migration/source"
    ingestion_inbox_path: Path = PROJECT_ROOT / "data/ingestion/inbox_reviews.json"
    release_finalizer_poll_seconds: float = 5.0
    deployment_revision: str = "local"

    extraction_backend: str = "codex_cli"
    extraction_model: str = "gpt-6-luna"
    extraction_reasoning_effort: str = "high"
    openai_api_key: str | None = Field(default=None, repr=False)
    codex_cli_executable: str = "codex"
    extraction_timeout_seconds: int = 180
    extraction_max_workers: int = 4

    embedding_backend: str = "sentence_transformer"
    embedding_model_id: str = (
        "snunlp/KR-SBERT-Medium-extended-klueNLItriplet_PARpair_QApair-klueSTS"
    )
    embedding_model_path: Path | None = (
        PROJECT_ROOT
        / "models/snunlp--KR-SBERT-Medium-extended-klueNLItriplet_PARpair_QApair-klueSTS"
    )
    embedding_batch_size: int = 32
    embedding_device: str = "cpu"
    embedding_local_files_only: bool = True
    taxonomy_rebuild_candidate_threshold: int = 100

    @field_validator("embedding_model_path", mode="before")
    @classmethod
    def empty_embedding_model_path_is_none(cls, value: object) -> object:
        return None if value == "" else value

    @property
    def work_root(self) -> Path:
        return self.catalog_data_root / "work"

    @property
    def release_staging_root(self) -> Path:
        return self.catalog_data_root / "release-staging"

    @property
    def release_root(self) -> Path:
        return self.catalog_data_root / "releases"

    @property
    def writer_lock_path(self) -> Path:
        return self.catalog_data_root / "locks" / "duckdb-writer.lock"

    def ensure_directories(self) -> None:
        for path in (
            self.work_root,
            self.release_staging_root,
            self.release_root,
            self.writer_lock_path.parent,
        ):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
