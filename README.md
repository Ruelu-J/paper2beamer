# paper2beamer

Convert academic papers (PDF) into professional Beamer (LaTeX) presentations — fully automated.

> Upload a PDF → get a `.zip` with compilable `.tex`, compiled `.pdf`, images, and build log.

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
- LaTeX distribution with `latexmk` ([TeX Live](https://tug.org/texlive/) recommended)
- [MinerU Cloud API key](https://mineru.net/apiManage/token) (free)
- (Optional) LLM API key for better slide quality ([SiliconFlow](https://siliconflow.cn) has a free tier)

### Install

```bash
git clone https://github.com/Ruelu-J/paper2beamer.git
cd paper2beamer
pip install -e .
```

### Run

```bash
# 1. Configure
cp .env.example .env
# Edit .env: set MINERU_API_KEY, LLM_API_KEY, TEX_ENGINE

# 2. Start web server
paper2beamer serve --port 8000
# Open http://localhost:8000

# 3. Or use CLI
paper2beamer convert paper.pdf --mode full -o output.zip
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

paper2beamer uses the OpenAI-compatible `/chat/completions` endpoint. Any provider works:

| Provider | `LLM_BASE_URL` | Free tier |
|----------|---------------|-----------|
| [SiliconFlow](https://siliconflow.cn) | `https://api.siliconflow.cn/v1` | Yes |
| [OpenAI](https://platform.openai.com) | `https://api.openai.com/v1` | No |
| [DeepSeek](https://platform.deepseek.com) | `https://api.deepseek.com/v1` | No |
| [Groq](https://console.groq.com) | `https://api.groq.com/openai/v1` | Yes |

Enter any model ID your provider supports in the web UI (text field, not dropdown).

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
- LaTeX distribution with `latexmk` (TeX Live recommended)
- MinerU Cloud API key (free at [mineru.net](https://mineru.net))
- (Optional) LLM API key for enhanced slide quality

## License

MIT
