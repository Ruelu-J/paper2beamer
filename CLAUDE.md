# CLAUDE.md

This file provides guidance to Claude when working with the paper2beamer repository.

## Project Overview

paper2beamer converts math/statistics papers (PDF) into Beamer (LaTeX) presentations. It extracts content from PDFs using MinerU, parses the Markdown output into a structured document model, converts it to Beamer LaTeX, splits content into properly-sized frames, compiles the LaTeX with latexmk, and packages everything in a downloadable ZIP.

## Build & Run Commands

```bash
# Install in development mode
pip install -e .

# Install with MinerU (local extraction)
pip install -e ".[mineru]"

# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Start web server
paper2beamer serve --port 8000

# CLI conversion (abstract mode)
paper2beamer convert pdf/2309.02211v5.pdf --mode abstract -o output.zip

# CLI conversion (full paper mode)
paper2beamer convert pdf/2309.02211v5.pdf --mode full -o output.zip

# Docker build & run
docker build -t paper2beamer .
docker run -p 8000:8000 paper2beamer

# Docker Compose (with local MinerU)
docker-compose up
```

## Architecture

```
PDF → MinerU → Markdown → Parser → Document → LLM Converter → Beamer LaTeX → Compiler → PDF → ZIP
```

### Key Modules

- `paper2beamer/core/models.py` — Domain dataclasses: Document, Section, Block, ExtractResult
- `paper2beamer/core/extractor.py` — MinerU abstraction (local API, CLI, cloud SDK with SSL workaround)
- `paper2beamer/core/parser.py` — MinerU Markdown → structured Document
- `paper2beamer/core/converter.py` — Document → Beamer LaTeX source (programmatic)
- `paper2beamer/core/llm_converter.py` — LLM-powered Beamer converter (template-aware, batched, compile-and-fix)
- `paper2beamer/core/splitter.py` — Frame splitting with line estimation heuristic
- `paper2beamer/core/compiler.py` — latexmk wrapper for PDF compilation
- `paper2beamer/core/citations.py` — Citation detection and .bib generation
- `paper2beamer/core/templates.py` — Beamer template ZIP validation/installation
- `paper2beamer/cache/manager.py` — SHA-256 content-addressed filesystem cache
- `paper2beamer/worker/tasks.py` — End-to-end processing pipeline with step_log tracking
- `paper2beamer/config.py` — pydantic-settings configuration (env vars + .env)

### API (FastAPI)

- `POST /api/upload` — Upload PDF, start background conversion
- `GET /api/jobs/{id}` — Poll job status
- `GET /api/jobs/{id}/download` — Download result ZIP
- `GET/POST/DELETE /api/templates` — Template management
- `GET/PUT /api/settings` — Configuration

### Web UI

- Jinja2 templates at `paper2beamer/web/templates/`
- Uses htmx for dynamic status updates (no SPA framework)
- CSS at `paper2beamer/web/static/css/main.css`

## Key Constraints

- Frame overflow: Splitter uses ~28 line max per frame heuristic. `allowframebreaks` as last resort.
- Template ZIPs: Must contain at least one .sty file, no path traversal, size < 50MB, < 50 files.
- Output ZIP: Always contains .tex, .pdf, build.log, README.txt, images/. .bib only in full mode.
- Caching: PDF SHA-256 hash → filesystem cache at `data/cache/{first2hex}/{full_hash}/`.
- LaTeX: Requires texlive + latexmk installed. Set via `TEX_ENGINE` env var (pdflatex/xelatex/lualatex).

## Environment Variables

Copy `.env.example` to `.env` and configure:
- `MINERU_MODE` — "local", "cli", or "cloud"
- `MINERU_API_KEY` — Cloud API key (free from mineru.net)
- `MINERU_API_URL` — Local mineru-api endpoint
- `TEX_ENGINE` — pdflatex (default), xelatex, or lualatex
- `DATABASE_URL` — SQLite path
- `SECRET_KEY` — Change in production

## Test PDF

`pdf/2309.02211v5.pdf` — "Distributionally Robust Learning for Multi-Source Unsupervised Domain Adaptation" (statistics paper with formulas, figures, tables, citations).

## Testing Conventions

- **Always test with the SUDA Beamer template**: The template ZIP is at `pdf/SUDA-Beamer-Theme-main.zip`. Install it first with `paper2beamer template install pdf/SUDA-Beamer-Theme-main.zip --name suda`, then pass it to convert: `paper2beamer convert pdf/2309.02211v5.pdf --mode full --template <template_dir_path>`.
- **Test both modes**: Always verify both `--mode abstract` and `--mode full` after making changes to the LLM converter or pipeline.
- **Keep test outputs**: Do NOT delete test output ZIPs or directories after testing — the user wants to inspect them.
- **Check frame count and content completeness**: After conversion, verify the output `.tex` has a reasonable number of frames (full mode: ~50+ frames) and that all sections of the paper appear.
- **Rich Unicode errors are non-fatal**: On Windows, `UnicodeEncodeError` from Rich's spinner is a display issue only — the conversion completes fine. Use direct Python scripts for reliable output.
