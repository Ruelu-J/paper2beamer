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

    # LLM (optional — for better slide quality)
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o"

    # LaTeX
    tex_engine: str = "pdflatex"
    latex_timeout: int = 300
    latex_runs: int = 2
    # How many times the LLM may retry fixing compile errors before giving
    # up. Each attempt = 1 LLM call + 1 latexmk run.
    llm_fix_attempts: int = 5

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
