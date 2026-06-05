# paper2beamer

Convert academic papers (PDF) into professional Beamer (LaTeX) presentations — fully automated.


## Features

- **PDF → Beamer pipeline**: Extracts text, formulas, tables, and figures; generates styled Beamer slides
- **LLM-enhanced conversion**: Uses LLM (any OpenAI-compatible API) to produce well-structured, template-aware Beamer output
- **Two modes**: Abstract-only (5–8 frames) or Full paper (50+ frames with all sections)
- **Template support**: Upload custom Beamer theme ZIPs; LLM respects template colors, fonts, and frame styles
- **Caching**: SHA-256 content-addressed cache skips re-extraction of previously processed PDFs
- **Web UI + CLI**: Browser-based interface with htmx live progress, plus command-line tool
- **Compile-and-fix**: LLM-powered LaTeX error repair loop (up to 5 retries) — no manual debugging needed

## Quick Start

### Prerequisites

- Python 3.10+
- **LaTeX distribution** with `latexmk` — see [LaTeX Installation](#latex-installation) below
- [MinerU Cloud API key](https://mineru.net/apiManage/token) (free registration)
- LLM API key (e.g. [SiliconFlow](https://siliconflow.cn), [DeepSeek](https://platform.deepseek.com), or [OpenAI](https://platform.openai.com))

### Install

```bash
git clone https://github.com/Ruelu-J/paper2beamer.git
cd paper2beamer
pip install -e .
```

### Web UI (recommended)

The web UI lets you configure everything on the page — no `.env` file needed. **LaTeX must be installed separately** (see [LaTeX Installation](#latex-installation)).

```bash
paper2beamer serve --port 8000
# Open http://localhost:8000
```

Then fill in your API keys directly in the sidebar settings. The server stores them in memory for the session.

### CLI

The CLI reads configuration from environment variables. First copy and edit `.env`:

```bash
cp .env.example .env
# Edit .env: set MINERU_API_KEY, LLM_API_KEY, TEX_ENGINE

# Then run:
paper2beamer convert paper.pdf --mode full -o output.zip
```

Or pass settings directly:

```bash
paper2beamer convert paper.pdf --mode full \
    --mineru-mode cloud --mineru-key $MINERU_KEY \
    --llm-model deepseek-ai/DeepSeek-V3.2 -o output.zip
```

### Docker

```bash
docker-compose up
```

## Pipeline

```
PDF ──→ MinerU ──→ Markdown ──→ Parser ──→ Document ──→ LLM Converter ──→ Beamer .tex ──→ Compiler ──→ PDF ──→ ZIP
         (cloud              (structured             (template-aware            (latexmk)          (final
          API)                sections)               LaTeX generation)                            download)
```

| Step | What happens | Time (typical) |
|------|-------------|----------------|
| 1. Extract | MinerU cloud API extracts text, math, tables, images | 2–3 min (cached after first run) |
| 2. Parse | Markdown → structured Document (sections, blocks) | < 1 sec |
| 3. Convert | LLM generates Beamer LaTeX following your template | 3–8 min (parallel batched calls) |
| 4. Compile | `latexmk` compiles to PDF; LLM auto-fixes errors | 30 sec–2 min |
| 5. Package | ZIP with `.tex`, `.pdf`, images, build log | < 1 sec |

## Configuration

Copy `.env.example` to `.env`:

```bash
# MinerU (PDF extraction)
MINERU_MODE=cloud                              # "local", "cli", or "cloud"
MINERU_API_KEY=your_mineru_key_here            # Get free key at mineru.net
MINERU_API_URL=http://localhost:8001           # Only for local mode

# LLM (slide generation — optional but recommended)
LLM_API_KEY=your_llm_key_here                  # OpenAI-compatible API key
LLM_BASE_URL=https://api.siliconflow.cn/v1     # API endpoint
LLM_MODEL=deepseek-ai/DeepSeek-V3.2

# LaTeX
TEX_ENGINE=xelatex                             # pdflatex, xelatex, or lualatex
LATEX_TIMEOUT=300
LLM_FIX_ATTEMPTS=5                             # Max auto-repair retries

# Storage
DATA_DIR=./data
CACHE_DIR=./data/cache

# Web
HOST=0.0.0.0
PORT=8000
MAX_UPLOAD_SIZE_MB=50
SECRET_KEY=change-me-in-production
```

### LLM Provider Setup

paper2beamer uses the OpenAI-compatible `/chat/completions` endpoint. Any provider that supports this API works. Common options:

Set `LLM_MODEL` to any model ID your provider supports. In the web UI, type the model name directly in the text field.

## LaTeX Installation

The pipeline compiles `.tex` to `.pdf` via `latexmk`, which requires a TeX distribution. If `latexmk` is not found, the output ZIP will still include the `.tex` file (you can compile it later), but the `.pdf` will be skipped.

### Windows

Install [MiKTeX](https://miktex.org/download) or [TeX Live](https://tug.org/texlive/windows.html). After installation, ensure `latexmk` is on your PATH:

```powershell
# Verify installation
latexmk --version
```

### macOS

Install [MacTeX](https://tug.org/mactex/):

```bash
brew install --cask mactex
# or download from https://tug.org/mactex/mactex-download.html
```

### Linux (Ubuntu/Debian)

```bash
sudo apt update
sudo apt install texlive-full latexmk
```

For a minimal install (faster, ~500 MB instead of ~5 GB):

```bash
sudo apt install texlive-latex-recommended texlive-latex-extra \
    texlive-fonts-recommended texlive-science latexmk
```

### Verify

```bash
latexmk --version
# Should print version info, e.g. "Latexmk, John Collins, ..."
```

## Web UI

### Main Page
- **Upload zone**: Drag & drop PDF, select mode (Full / Abstract Only)
- **Settings sidebar**: Configure MinerU, LLM, LaTeX engine, template
- **Live progress**: Step-by-step timeline with elapsed time and progress bar
- **Job history**: Recent conversions with status badges

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/upload` | Upload PDF, start conversion |
| `GET` | `/api/jobs/{id}` | JSON job status |
| `GET` | `/api/jobs/{id}/html` | HTML fragment (htmx polling) |
| `GET` | `/api/jobs/{id}/download` | Download result ZIP |
| `GET` | `/api/jobs/{id}/download/pdf` | Download compiled PDF |
| `GET/PUT` | `/api/settings` | Read/update configuration |
| `GET/POST/DELETE` | `/api/templates` | Manage Beamer templates |

## CLI

```bash
# Full paper conversion
paper2beamer convert paper.pdf --mode full -o output.zip

# Abstract-only (5-8 slides from title + abstract)
paper2beamer convert paper.pdf --mode abstract -o output.zip

# With custom template
paper2beamer template install my-theme.zip --name mytheme
paper2beamer convert paper.pdf --mode full --template mytheme -o output.zip

# Override settings
paper2beamer convert paper.pdf --mode full \
    --mineru-mode cloud --mineru-key $KEY \
    --llm-model deepseek-ai/DeepSeek-V3.2 -o output.zip
```

## Project Structure

```
paper2beamer/
├── paper2beamer/
│   ├── core/                  # Domain logic
│   │   ├── extractor.py       # MinerU abstraction (cloud / local / CLI)
│   │   ├── parser.py          # Markdown → structured Document
│   │   ├── converter.py       # Traditional Beamer LaTeX generator
│   │   ├── llm_converter.py   # LLM-powered Beamer generator (template-aware)
│   │   ├── splitter.py        # Frame splitting heuristics
│   │   ├── compiler.py        # latexmk wrapper
│   │   ├── citations.py       # Citation detection + .bib generation
│   │   ├── templates.py       # Template ZIP validation/installation
│   │   ├── models.py          # Domain dataclasses
│   │   └── hashing.py         # SHA-256 content hashing
│   ├── api/                   # FastAPI routes
│   │   ├── routes/            # jobs.py, upload.py, settings.py, templates.py
│   │   └── schemas.py         # Pydantic request/response models
│   ├── web/                   # Jinja2 templates + static CSS
│   ├── cli/                   # Click CLI
│   ├── db/                    # SQLAlchemy models + async engine
│   ├── cache/                 # SHA-256 filesystem cache manager
│   ├── worker/                # Background job processing pipeline
│   └── config.py              # pydantic-settings (env vars + .env)
├── tests/                     # Pytest test suite
├── templates/default/         # Built-in Beamer theme
├── pyproject.toml
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run end-to-end test
python test_e2e.py
```

## Requirements

- Python 3.10+
- LaTeX distribution with `latexmk` — [Installation guide](#latex-installation)
- MinerU Cloud API key (free registration at [mineru.net](https://mineru.net))
- LLM API key for enhanced slide quality

