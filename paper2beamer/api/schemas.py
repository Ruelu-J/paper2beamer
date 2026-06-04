"""Pydantic request/response schemas for the API."""

from pydantic import BaseModel, Field
from datetime import datetime


class UploadResponse(BaseModel):
    job_id: str
    status: str
    message: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    mode: str | None = None
    pdf_filename: str | None = None
    pdf_hash: str | None = None
    progress_percent: int = 0
    error_message: str | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None


class TemplateInfo(BaseModel):
    id: str
    name: str
    description: str | None = None
    is_default: bool = False
    created_at: datetime | None = None


class TemplateListResponse(BaseModel):
    templates: list[TemplateInfo]


class TemplateInstallResponse(BaseModel):
    template_id: str
    name: str
    message: str


class SettingsInfo(BaseModel):
    mineru_mode: str
    mineru_api_url: str
    mineru_api_key_set: bool
    tex_engine: str
    llm_api_key_set: bool = False
    llm_model: str = "gpt-4o"


class SettingsUpdate(BaseModel):
    mineru_mode: str | None = None
    mineru_api_key: str | None = None
    mineru_api_url: str | None = None
    tex_engine: str | None = None


class MessageResponse(BaseModel):
    message: str
