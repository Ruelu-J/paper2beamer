"""Application configuration via environment variables."""

from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    # MinerU
    mineru_mode: str = "local"  # "local" or "cloud"
    mineru_api_key: str = ""
    mineru_api_url: str = "http://localhost:8001"
    mineru_timeout: int = 300

    # Storage
    data_dir: str = "./data"
    cache_dir: str = "./data/cache"
    output_dir: str = "./data/outputs"
    template_dir: str = "./data/templates"

    # LaTeX
    tex_engine: str = "pdflatex"
    latex_timeout: int = 120
    latex_runs: int = 2

    # Database
    database_url: str = "sqlite+aiosqlite:///./data/paper2beamer.db"

    # Web
    host: str = "0.0.0.0"
    port: int = 8000
    max_upload_size_mb: int = 50
    secret_key: str = "change-me-in-production"

    def resolve_path(self, path: str) -> Path:
        p = Path(path)
        if p.is_absolute():
            return p
        return p.resolve()


settings = Settings()
