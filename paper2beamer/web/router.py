"""Web UI routes — renders Jinja2 HTML pages."""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from paper2beamer.config import settings

templates_dir = Path(__file__).parent / "templates"
jinja = Jinja2Templates(directory=str(templates_dir))

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return jinja.TemplateResponse("index.html.j2", {
        "request": request,
        "max_upload_mb": settings.max_upload_size_mb,
    })


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_page(request: Request, job_id: str):
    return jinja.TemplateResponse("job.html.j2", {
        "request": request,
        "job_id": job_id,
    })


@router.get("/templates", response_class=HTMLResponse)
async def templates_page(request: Request):
    return jinja.TemplateResponse("templates.html.j2", {
        "request": request,
    })


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    return jinja.TemplateResponse("settings.html.j2", {
        "request": request,
    })
