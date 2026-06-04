"""Web UI routes — renders Jinja2 HTML pages."""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from paper2beamer.config import settings
from paper2beamer.db.models import UserTemplate

templates_dir = Path(__file__).parent / "templates"
jinja = Jinja2Templates(directory=str(templates_dir))

router = APIRouter()


async def _get_templates() -> list[dict]:
    """Load installed templates from DB."""
    from paper2beamer.db.database import get_session_factory

    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(UserTemplate).order_by(UserTemplate.created_at.desc())
        result = await session.execute(stmt)
        entries = result.scalars().all()
        return [
            {"id": t.id, "name": t.name, "description": t.description}
            for t in entries
        ]


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    templates = await _get_templates()
    return jinja.TemplateResponse("index.html.j2", {
        "request": request,
        "max_upload_mb": settings.max_upload_size_mb,
        "mineru_mode": settings.mineru_mode,
        "mineru_api_url": settings.mineru_api_url,
        "mineru_api_key_set": bool(settings.mineru_api_key),
        "tex_engine": settings.tex_engine,
        "llm_api_key_set": bool(settings.llm_api_key),
        "llm_base_url": settings.llm_base_url,
        "llm_model": settings.llm_model,
        "templates": templates,
    })
