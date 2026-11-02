"""Central project settings loaded from environment variables."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Filesystem locations used by local pipelines."""

    project_env: str = "development"
    data_root: Path = Path("data")
    raw_data_dir: Path = Path("data/raw")
    bronze_data_dir: Path = Path("data/bronze")
    silver_data_dir: Path = Path("data/silver")
    offline_store_dir: Path = Path("data/offline_store")
    reports_dir: Path = Path("reports/generated")
    synthetic_epoch: str = "2017-01-01T00:00:00Z"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

