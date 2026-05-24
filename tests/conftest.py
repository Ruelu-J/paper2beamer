"""Test fixtures for paper2beamer."""

import pytest
from pathlib import Path


@pytest.fixture
def sample_markdown() -> str:
    fixture_path = Path(__file__).parent / "fixtures" / "sample_markdown.md"
    return fixture_path.read_text(encoding="utf-8")


@pytest.fixture
def sample_pdf_path() -> Path:
    return Path(__file__).parent.parent / "pdf" / "2309.02211v5.pdf"


@pytest.fixture
def default_template_dir() -> str:
    return str(Path(__file__).parent.parent / "templates" / "default")
