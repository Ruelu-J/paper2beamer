"""Settings endpoints — configure MinerU, LaTeX, LLM, etc."""

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from paper2beamer.api.schemas import SettingsInfo, MessageResponse
from paper2beamer.config import settings

router = APIRouter()

# Track output mode (not in .env, runtime only)
_output_mode: str = "full"


@router.get("/settings", response_model=SettingsInfo)
async def get_settings():
    return SettingsInfo(
        mineru_mode=settings.mineru_mode,
        mineru_api_url=settings.mineru_api_url,
        mineru_api_key_set=bool(settings.mineru_api_key),
        tex_engine=settings.tex_engine,
        llm_api_key_set=bool(settings.llm_api_key),
        llm_model=settings.llm_model,
    )


@router.put("/settings")
async def update_settings(
    request: Request,
    mineru_mode: str | None = Form(default=None),
    mineru_api_key: str | None = Form(default=None),
    mineru_api_url: str | None = Form(default=None),
    tex_engine: str | None = Form(default=None),
    llm_api_key: str | None = Form(default=None),
    llm_base_url: str | None = Form(default=None),
    llm_model: str | None = Form(default=None),
):
    if mineru_mode is not None:
        settings.mineru_mode = mineru_mode
    if mineru_api_key is not None and mineru_api_key.strip():
        settings.mineru_api_key = mineru_api_key.strip()
    if mineru_api_url is not None:
        settings.mineru_api_url = mineru_api_url
    if tex_engine is not None:
        settings.tex_engine = tex_engine
    if llm_api_key is not None and llm_api_key.strip():
        settings.llm_api_key = llm_api_key.strip()
    if llm_base_url is not None and llm_base_url.strip():
        settings.llm_base_url = llm_base_url.strip()
    if llm_model is not None:
        settings.llm_model = llm_model

    is_htmx = request.headers.get("HX-Request") == "true"
    if is_htmx:
        return HTMLResponse(
            '<span class="success-msg">Settings saved.</span>'
        )
    return MessageResponse(message="Settings updated.")


@router.post("/settings/mode")
async def set_output_mode(
    request: Request,
    output_mode: str = Form(default="full"),
):
    global _output_mode
    if output_mode in ("abstract", "full"):
        _output_mode = output_mode

    is_htmx = request.headers.get("HX-Request") == "true"
    if is_htmx:
        return HTMLResponse(
            f'<span class="success-msg">Mode: {_output_mode}</span>'
        )
    return MessageResponse(message=f"Output mode set to {_output_mode}")
