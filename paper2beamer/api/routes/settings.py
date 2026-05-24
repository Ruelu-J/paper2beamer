"""Settings endpoints — configure MinerU, LaTeX, etc."""

from fastapi import APIRouter

from paper2beamer.api.schemas import SettingsInfo, SettingsUpdate, MessageResponse
from paper2beamer.config import settings

router = APIRouter()


@router.get("/settings", response_model=SettingsInfo)
async def get_settings():
    return SettingsInfo(
        mineru_mode=settings.mineru_mode,
        mineru_api_url=settings.mineru_api_url,
        mineru_api_key_set=bool(settings.mineru_api_key),
        tex_engine=settings.tex_engine,
    )


@router.put("/settings", response_model=MessageResponse)
async def update_settings(body: SettingsUpdate):
    if body.mineru_mode is not None:
        settings.mineru_mode = body.mineru_mode
    if body.mineru_api_key is not None:
        settings.mineru_api_key = body.mineru_api_key
    if body.mineru_api_url is not None:
        settings.mineru_api_url = body.mineru_api_url
    if body.tex_engine is not None:
        settings.tex_engine = body.tex_engine
    return MessageResponse(message="Settings updated.")
