# paper2beamer

Convert math/statistics papers (PDF) into Beamer (LaTeX) presentations.

## Features

- **PDF to Beamer**: Extract formulas, tables, and figures from PDFs and convert to well-formatted Beamer slides
- **Two output modes**: Abstract-only or full paper (with split `.bib` file)
- **Custom templates**: Upload your own Beamer theme as a ZIP file
- **Content-aware splitting**: Automatically splits content across frames so nothing overflows
- **Caching**: SHA-256 based cache to skip re-extraction of previously processed PDFs
- **Web UI + CLI**: Browser-based upload interface and command-line tool
- **Self-deployable**: Docker Compose with optional GPU acceleration

## Quick Start

### Install

```bash
pip install -e .
```

### CLI Usage

```bash
# Abstract mode
paper2beamer convert paper.pdf --mode abstract -o presentation.zip

# Full paper mode
paper2beamer convert paper.pdf --mode full -o presentation.zip

# With custom template
paper2beamer convert paper.pdf --mode full --template mytheme.zip -o out.zip
```

### Web Server

```bash
paper2beamer serve --port 8000
# Open http://localhost:8000
```

### Docker

```bash
docker-compose up
```

## How It Works

```
PDF → MinerU → Markdown → Parser → Beamer LaTeX → Splitter → Compiler → PDF → ZIP
```

1. **Extract**: MinerU converts PDF to Markdown (preserving math LaTeX, tables, images)
2. **Parse**: Structured document model (sections, blocks, citations)
3. **Convert**: Beamer LaTeX generation with template integration
4. **Split**: Content divided into frames using line-height heuristics
5. **Compile**: `latexmk` compiles to PDF
6. **Package**: ZIP containing `.tex`, `.pdf`, `.bib`, images, and build log

## MinerU Setup

### Option A: Local MinerU (recommended)

```bash
pip install "mineru[all]"
mineru-api --host 0.0.0.0 --port 8001
```

### Option B: Cloud API

```bash
pip install mineru-open-sdk
# Set MINERU_MODE=cloud and MINERU_API_KEY in .env
```

Get a free API key at [mineru.net](https://mineru.net/apiManage/token).

### Option C: Docker MinerU

Included in `docker-compose.yml`.

## Configuration

Copy `.env.example` to `.env` and configure:

| Variable | Description | Default |
|----------|-------------|---------|
| `MINERU_MODE` | `local`, `cli`, or `cloud` | `local` |
| `MINERU_API_KEY` | Cloud API key | - |
| `MINERU_API_URL` | Local mineru-api URL | `http://localhost:8001` |
| `TEX_ENGINE` | `pdflatex`, `xelatex`, or `lualatex` | `pdflatex` |
| `DATABASE_URL` | SQLite path | `sqlite+aiosqlite:///./data/paper2beamer.db` |

## Requirements

- Python 3.10+
- LaTeX distribution (texlive recommended, with `latexmk`)
- MinerU (local install or cloud API key)

## Project Structure

```
paper2beamer/
├── paper2beamer/          # Main package
│   ├── core/              # Domain logic (extractor, parser, converter, splitter, compiler)
│   ├── api/               # FastAPI routes
│   ├── web/               # Jinja2 templates + static files
│   ├── cli/               # Click CLI
│   ├── db/                # SQLAlchemy models
│   ├── cache/             # Filesystem cache manager
│   └── worker/            # Background job processing
├── templates/default/     # Built-in Beamer theme
├── tests/                 # Test suite
├── Dockerfile
├── docker-compose.yml
└── CLAUDE.md
```

## License

MIT
